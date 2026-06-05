"""Layout and styling constants shared across the tray UI modules."""
from __future__ import annotations

_MEDIA_PROFILE_COLUMNS = 3
_MEDIA_ICON_PIXELS = 22
_PROFILE_ICON_PIXELS = 28
_DISPLAY_GRID_COLUMNS = 2
_DISPLAY_CARD_SIZE = 140
_DISPLAY_CARD_GAP = 2
_DISPLAY_CARD_MARGIN = 8
# Compact faceplate budget: a display with no audio/volume control drops the
# tall volume bar, so the card only needs the title plus the action buttons.
_DISPLAY_TITLE_HEIGHT = 38
_DISPLAY_ACTION_ROW_HEIGHT = 32
_DISPLAY_POWER_BUTTON_WIDTH = 40
# No gap between the action buttons: the Enable/Disable button sits flush
# against the power on/off pair and spans exactly their combined width.
_DISPLAY_BUTTON_SPACING = 0
_DISPLAY_TOGGLE_BUTTON_WIDTH = (
    _DISPLAY_POWER_BUTTON_WIDTH * 2 + _DISPLAY_BUTTON_SPACING
)

