# 20 — VR feasibility

**Status: deferred (D149).** This is the feasibility spike requested after the render work; it does not
add a VR runtime to the app.

## What is available

- `openxr-sdk` **1.1.65** is on conda-forge (C/C++ headers and loader), so the OpenXR API itself can be
  compiled against from the pixi environment.
- The renderer is OCCT/OpenGL through `V3d_View` and Qt 6, already used for the offscreen renderer.
- No headset, no OpenXR runtime (SteamVR / Windows Mixed Reality / Monado) and no driver is available in
  the development or CI environment, so a session cannot be created or tested here.

## What a VR mode needs

1. **OpenXR session + runtime**: create an instance, system, session and swapchain; handle
   `XR_KHR_D3D11_enable` on Windows and `XR_KHR_opengl_enable` on Linux.
2. **Per-eye rendering**: two projection matrices and two viewports per frame. OCCT can render to an
   offscreen image (`Viewport::renderImage` / `renderPhoto`), but the current `V3d_View` owns one
   window; a stereo path needs either two viewports in one FBO or a dedicated render target.
3. **Frame timing**: the OpenXR runtime drives the frame loop; the app must switch from Qt event-driven
   painting to `xrWaitFrame`/`xrBeginFrame`/`xrEndFrame` while a session is running.
4. **Input**: controller poses and actions (navigate, teleport) via OpenXR action sets.
5. **UI/UX**: a comfort mode, recentering, seated/standing spaces, and a way to return to the desktop.
6. **Packaging and QA**: OpenXR loader/runtime deployment and a headset for every release check.

## Cost and risk

- Estimated **2–4 weeks** for a usable walk-around/teleport viewer on one platform, more for two eyes
  with proper depth and controller interaction.
- Cannot be verified without a headset; shipping untested VR would violate the project’s evidence rule.
- The existing 2D/3D viewport and high-resolution/ray-traced exports already cover presentation needs
  for architects; VR is a viewing extra, not an authoring requirement.

## Recommendation

Defer VR until the owner provides (a) an OpenXR runtime/headset for testing and (b) a decision that VR
is in scope. The integration should then be an opt-in plugin behind `openxr-sdk`, leaving the desktop
renderer untouched.
