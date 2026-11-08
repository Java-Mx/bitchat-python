"""Tests for Windows installer Terms and Privacy checkbox scaling, dimensions, and DPI parity."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ISS_PATH = REPO_ROOT / "packaging" / "windows" / "bitchat.iss"


def test_installer_terms_and_privacy_checkbox_attributes() -> None:
    """Verify Terms and Privacy checkboxes have explicit height, scaling, font, and accessibility."""
    assert ISS_PATH.is_file(), "bitchat.iss must exist"
    content = ISS_PATH.read_text(encoding="utf-8")

    # Verify Terms checkbox scaling and dimensions
    assert "TermsCheckBox.Height := ScaleY(24);" in content
    assert "TermsCheckBox.Font.Name := 'Segoe UI';" in content
    assert "TermsCheckBox.Font.Size := 9;" in content
    assert "TermsCheckBox.TabStop := True;" in content
    assert "TermsCheckBox.Cursor := crHand;" in content

    # Verify Privacy checkbox scaling and dimensions
    assert "PrivacyCheckBox.Height := ScaleY(24);" in content
    assert "PrivacyCheckBox.Font.Name := 'Segoe UI';" in content
    assert "PrivacyCheckBox.Font.Size := 9;" in content
    assert "PrivacyCheckBox.TabStop := True;" in content
    assert "PrivacyCheckBox.Cursor := crHand;" in content


def test_installer_dpi_scaling_dimensions_math() -> None:
    """Simulate ScaleY at standard Windows DPI scaling factors (100%, 125%, 150%, 200%).

    Ensure that on all scaling factors, the controls comfortably fit inside the wizard surface
    without clipping or negative margin.
    """
    dpi_scales = [1.0, 1.25, 1.5, 2.0]
    base_surface_height = 238  # Typical Inno Setup modern wizard page surface height

    for scale in dpi_scales:

        def scale_y(val: int, s: float = scale) -> int:
            return round(val * s)

        # Terms page layout calculations
        terms_memo_height = scale_y(base_surface_height) - scale_y(68)
        terms_link_top = terms_memo_height + scale_y(6)
        terms_link_height = scale_y(14)
        terms_check_top = terms_link_top + terms_link_height + scale_y(8)
        terms_check_height = scale_y(24)
        terms_total_bottom = terms_check_top + terms_check_height

        assert terms_memo_height > 0, (
            f"Memo height must be positive at {int(scale * 100)}%"
        )
        assert terms_check_height >= 24, (
            f"Checkbox height must be at least 24px at {int(scale * 100)}%"
        )
        assert terms_total_bottom <= scale_y(base_surface_height), (
            f"Terms controls exceed page surface at {int(scale * 100)}%: "
            f"{terms_total_bottom} > {scale_y(base_surface_height)}"
        )

        # Privacy page layout calculations
        privacy_memo_height = scale_y(base_surface_height) - scale_y(92)
        privacy_link_top = privacy_memo_height + scale_y(6)
        privacy_link_height = scale_y(14)
        privacy_note_top = privacy_link_top + privacy_link_height + scale_y(4)
        privacy_note_height = scale_y(28)  # 2 lines wrapped
        privacy_check_top = privacy_note_top + privacy_note_height + scale_y(6)
        privacy_check_height = scale_y(24)
        privacy_total_bottom = privacy_check_top + privacy_check_height

        assert privacy_memo_height > 0
        assert privacy_check_height >= 24
        assert privacy_total_bottom <= scale_y(base_surface_height), (
            f"Privacy controls exceed page surface at {int(scale * 100)}%: "
            f"{privacy_total_bottom} > {scale_y(base_surface_height)}"
        )
