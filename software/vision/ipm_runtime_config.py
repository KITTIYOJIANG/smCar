# Optional target-area inverse perspective mapping for OpenART/OpenMV runtime scripts.
#
# When enabled, the four source corners are stretched to the whole model input,
# so the model sees only the character panel instead of the full camera scene.

# Temporarily disabled for classifier label/output debugging. Enable it again
# only after the four corners are recalibrated for the current camera view.
USE_IPM = False

# Corner order: top-left, top-right, bottom-right, bottom-left.
# These QVGA defaults come from smartcar_roi_trainer/raw_full/GreyWolf/screen_010.jpg
# full-frame corners: (216,126), (407,128), (407,310), (207,310).
IPM_CORNERS = ((108, 63), (204, 64), (204, 155), (104, 155))

# False keeps the old image path alive if the firmware lacks rotation_corr().
IPM_FAIL_CLOSED = False
