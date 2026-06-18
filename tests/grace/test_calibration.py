"""
GRACE Calibration Tests（S1・Ollama 構成）

grace/calibration.py の温度スケーリング較正をユニット検証する。
LLM 非依存・決定的（外部サービス不要）。
"""

import math

from grace.calibration import (
    Calibrator,
    apply_temperature,
    expected_calibration_error,
    fit_temperature,
)


class TestApplyTemperature:
    """温度適用（apply_temperature）"""

    def test_identity_at_t1(self):
        """T=1.0 は恒等（入力をほぼそのまま返す）"""
        for p in (0.1, 0.5, 0.73, 0.9):
            assert abs(apply_temperature(p, 1.0) - p) < 1e-6

    def test_high_temperature_softens_overconfidence(self):
        """T>1.0 は高い confidence を引き下げる（0.5 へ寄せる）"""
        assert apply_temperature(0.9, 2.0) < 0.9
        assert apply_temperature(0.9, 2.0) > 0.5

    def test_low_temperature_sharpens(self):
        """T<1.0 は高い confidence をさらに押し上げる"""
        assert apply_temperature(0.8, 0.5) > 0.8

    def test_nonpositive_temperature_treated_as_identity(self):
        """T<=0 は 1.0 とみなす（恒等）"""
        assert abs(apply_temperature(0.7, 0.0) - 0.7) < 1e-6
        assert abs(apply_temperature(0.7, -3.0) - 0.7) < 1e-6

    def test_extremes_clipped(self):
        """0/1 付近でも発散しない"""
        assert 0.0 < apply_temperature(0.0, 1.5) < 1.0
        assert 0.0 < apply_temperature(1.0, 1.5) < 1.0


class TestFitTemperature:
    """温度推定（fit_temperature）"""

    def test_degenerate_all_correct_returns_identity(self):
        """全問正解は較正不能 → T=1.0"""
        assert fit_temperature([0.6, 0.7, 0.8], [True, True, True]) == 1.0

    def test_degenerate_all_wrong_returns_identity(self):
        assert fit_temperature([0.6, 0.7, 0.8], [False, False, False]) == 1.0

    def test_empty_returns_identity(self):
        assert fit_temperature([], []) == 1.0

    def test_overconfident_data_fits_temperature_above_one(self):
        """自信過剰（高 confidence なのに正解率が低い）→ T>1.0 を推定"""
        # confidence は高い（0.9）が、正解は半々 → 自信過剰
        confidences = [0.9] * 10
        correctness = [True, False] * 5
        t = fit_temperature(confidences, correctness)
        assert t > 1.0

    def test_fit_reduces_ece(self):
        """較正後 ECE が較正前以下になる（自信過剰データ）"""
        confidences = [0.95, 0.9, 0.92, 0.88, 0.9, 0.93, 0.91, 0.94, 0.89, 0.9]
        correctness = [True, False, False, False, True, False, False, True, False, False]
        ece_before = expected_calibration_error(confidences, correctness)
        t = fit_temperature(confidences, correctness)
        calibrated = [apply_temperature(p, t) for p in confidences]
        ece_after = expected_calibration_error(calibrated, correctness)
        assert ece_after <= ece_before + 1e-9


class TestExpectedCalibrationError:
    """ECE 計算"""

    def test_empty_is_zero(self):
        assert expected_calibration_error([], []) == 0.0

    def test_perfectly_calibrated_is_low(self):
        """confidence == 実正解率 のとき ECE は小さい"""
        # 0.0 confidence で全不正解、1.0 confidence で全正解
        confidences = [0.0, 0.0, 1.0, 1.0]
        correctness = [False, False, True, True]
        assert expected_calibration_error(confidences, correctness) < 1e-6

    def test_miscalibrated_is_positive(self):
        """confidence 1.0 なのに全不正解 → ECE≈1.0"""
        confidences = [1.0, 1.0, 1.0, 1.0]
        correctness = [False, False, False, False]
        assert expected_calibration_error(confidences, correctness) > 0.9


class TestCalibrator:
    """Calibrator（永続化・transform）"""

    def test_identity_default(self):
        c = Calibrator()
        assert c.is_identity()
        assert abs(c.transform(0.6) - 0.6) < 1e-6

    def test_transform_uses_temperature(self):
        c = Calibrator(temperature=2.0)
        assert not c.is_identity()
        assert c.transform(0.9) == apply_temperature(0.9, 2.0)

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "calibration.json"
        Calibrator(temperature=1.7).save(str(path))
        loaded = Calibrator.load(str(path))
        assert math.isclose(loaded.temperature, 1.7, rel_tol=1e-9)

    def test_load_missing_returns_identity(self, tmp_path):
        loaded = Calibrator.load(str(tmp_path / "does_not_exist.json"))
        assert loaded.is_identity()

    def test_load_corrupt_returns_identity(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert Calibrator.load(str(path)).is_identity()

    def test_fit_classmethod(self):
        c = Calibrator.fit([0.9] * 6, [True, False] * 3)
        assert c.temperature > 1.0
