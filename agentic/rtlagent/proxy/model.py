"""Learned PPA proxy (MasterRTL-style) with an analytical fallback.

MasterRTL trains one XGBoost regressor per target (area / WNS / TNS / power)
on SOG features against commercial-tool labels.  Here the labels come from
the harness's own yosys+ABC flow (``rtlagent.eda.synthesize``), so the proxy
can be bootstrapped on any machine: every full synthesis the harness runs is
also a free training sample, and the proxy improves as the run progresses.

Untrained, the proxy falls back to the analytical SOG estimates (est_wns /
est_tns / total_area scaled by a running calibration factor), so ranking
works out of the box.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .sog import FEATURE_NAMES, SOGFeatures, sog_features

log = logging.getLogger(__name__)

TARGETS = ("wns", "tns", "area")
MIN_SAMPLES_TO_TRAIN = 8


@dataclass
class ProxyPrediction:
    wns: float
    tns: float
    area: float
    source: str  # "model" | "analytical"

    def score(self, baseline: "ProxyPrediction") -> float:
        """Composite proxy score mirroring the Dr.RTL weights (lower=better)."""

        def norm(v: float, b: float) -> float:
            return abs(v) / abs(b) if abs(b) > 1e-9 else (0.0 if abs(v) < 1e-9 else 1.0 + abs(v))

        wns_term = norm(max(0.0, -self.wns), max(0.0, -baseline.wns)) if baseline.wns < 0 else 0.0
        tns_term = norm(max(0.0, -self.tns), max(0.0, -baseline.tns))
        return 0.5 * wns_term + 0.35 * tns_term + 0.15 * norm(self.area, baseline.area)


class PPAProxy:
    """Fast PPA estimator used to rank candidate RTL before full synthesis."""

    def __init__(self, model_path: Optional[str | Path] = None):
        self.model_path = Path(model_path) if model_path else None
        self.models: dict[str, object] = {}
        self.samples: list[tuple[list[float], dict[str, float]]] = []
        # Calibration of analytical estimates against observed ground truth.
        self._delay_scale = 1.0
        self._area_scale = 1.0
        if self.model_path and self.model_path.exists():
            self.load(self.model_path)

    # -- prediction ---------------------------------------------------------

    def predict_from_features(self, feats: SOGFeatures, clock_period: float) -> ProxyPrediction:
        vec = feats.vector()
        if self.models:
            pred = {t: float(self.models[t].predict([vec])[0]) for t in TARGETS}
            return ProxyPrediction(pred["wns"], pred["tns"], pred["area"], source="model")
        est_delay = feats.values["est_delay"] * self._delay_scale
        wns = clock_period - est_delay
        tns = feats.values["est_tns"] * self._delay_scale
        area = feats.values["total_area"] * self._area_scale
        return ProxyPrediction(wns, tns, area, source="analytical")

    def predict(
        self, files: Sequence[str | Path], top: str, clock_period: float
    ) -> Optional[ProxyPrediction]:
        feats = sog_features(files, top, clock_period)
        if feats is None:
            return None
        return self.predict_from_features(feats, clock_period)

    # -- online learning ----------------------------------------------------

    def add_sample(self, feats: SOGFeatures, wns: float, tns: float, area: float) -> None:
        """Feed back a ground-truth synthesis result (free training data)."""
        self.samples.append((feats.vector(), {"wns": wns, "tns": tns, "area": area}))
        # Keep the analytical fallback calibrated even before training kicks in.
        est_delay = feats.values["est_delay"]
        true_delay = feats.values["est_delay"]  # placeholder if wns unavailable
        if est_delay > 1e-6:
            # derive true delay from wns: delay = clock - wns; clock unknown
            # here, so calibrate on area only and delay via ratio of estimates.
            pass
        if feats.values["total_area"] > 1e-6 and area > 0:
            obs = area / feats.values["total_area"]
            self._area_scale = 0.7 * self._area_scale + 0.3 * obs
        if len(self.samples) >= MIN_SAMPLES_TO_TRAIN and len(self.samples) % 4 == 0:
            self.train()

    def calibrate_delay(self, est_delay: float, true_delay: float) -> None:
        if est_delay > 1e-6 and true_delay > 0:
            obs = true_delay / est_delay
            self._delay_scale = 0.7 * self._delay_scale + 0.3 * obs

    def train(self) -> bool:
        if len(self.samples) < MIN_SAMPLES_TO_TRAIN:
            return False
        try:
            from sklearn.ensemble import GradientBoostingRegressor
        except ImportError:
            log.warning("scikit-learn unavailable; proxy stays analytical")
            return False
        X = [s[0] for s in self.samples]
        for t in TARGETS:
            y = [s[1][t] for s in self.samples]
            # Shallow model: sample counts are small during a run.
            m = GradientBoostingRegressor(n_estimators=25, max_depth=4, learning_rate=0.1)
            m.fit(X, y)
            self.models[t] = m
        log.info("proxy trained on %d samples", len(self.samples))
        if self.model_path:
            self.save(self.model_path)
        return True

    # -- persistence ----------------------------------------------------------

    def save(self, path: str | Path) -> None:
        payload = {
            "models": self.models,
            "samples": self.samples,
            "delay_scale": self._delay_scale,
            "area_scale": self._area_scale,
            "feature_names": FEATURE_NAMES,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(pickle.dumps(payload))

    def load(self, path: str | Path) -> None:
        try:
            payload = pickle.loads(Path(path).read_bytes())
            self.models = payload.get("models", {})
            self.samples = payload.get("samples", [])
            self._delay_scale = payload.get("delay_scale", 1.0)
            self._area_scale = payload.get("area_scale", 1.0)
        except Exception as e:  # noqa: BLE001
            log.warning("failed to load proxy model from %s: %s", path, e)
