"""FP-02/04/05 — 결측 유지, registry 왕복, 저변동 제외, 버전 불일치 검증."""

import numpy as np
import pandas as pd
import pytest

from dry_process_ai.data_access.preprocess import RegistryVersionMismatch, ScalingRegistry


def _df():
    return pd.DataFrame({
        "feat_a": [1.0, 2.0, 3.0, 4.0],
        "feat_const": [5.0, 5.0, 5.0, 5.0],       # 저변동 — 자동 제외 대상 (FP-05)
        "target_x": [10.0, np.nan, 30.0, 40.0],    # 결측 포함 (FP-02)
    })


def test_nan_preserved_after_scaling():
    df = _df()
    reg = ScalingRegistry.fit(df, ["feat_a", "feat_const"], ["target_x"], version="v1.0")
    scaled = reg.transform(df, ["target_x"])
    assert np.isnan(scaled["target_x"].iloc[1])          # 0/평균 대체 금지
    assert scaled["target_x"].iloc[0] == 0.0
    assert scaled["target_x"].iloc[3] == 1.0


def test_low_variance_excluded():
    df = _df()
    reg = ScalingRegistry.fit(df, ["feat_a", "feat_const"], ["target_x"], version="v1.0")
    assert "feat_const" in reg.excluded_low_variance
    assert reg.feature_columns == ["feat_a"]


def test_inverse_transform_roundtrip():
    df = _df()
    reg = ScalingRegistry.fit(df, ["feat_a"], ["target_x"], version="v1.0")
    scaled = reg.transform(df, ["feat_a", "target_x"])
    restored = reg.inverse_transform(scaled, ["feat_a", "target_x"])
    pd.testing.assert_series_equal(restored["feat_a"], df["feat_a"], check_names=False)


def test_missing_mask():
    df = _df()
    reg = ScalingRegistry.fit(df, ["feat_a"], ["target_x"], version="v1.0")
    mask = reg.missing_mask(df, ["target_x"])
    assert mask["target_x"].tolist() == [1.0, 0.0, 1.0, 1.0]


def test_registry_version_mismatch_raises(tmp_path):
    # 규칙 R8: 모델-registry 짝 불일치 시 로드 실패해야 한다 (조용한 오류 방지)
    df = _df()
    reg = ScalingRegistry.fit(df, ["feat_a"], ["target_x"], version="v1.0")
    reg.save(tmp_path)
    loaded = ScalingRegistry.load("v1.0", tmp_path)
    assert loaded.version == "v1.0"
    with pytest.raises(RegistryVersionMismatch):
        ScalingRegistry.load("v1.0", tmp_path, expected_model_version="v2.0")
