// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QString>

namespace kimbim {

// Apply the Appearance preference: "system", "light" or "dark".
// The app uses Fusion for a predictable palette on every platform; native file dialogs stay native.
void applyTheme(const QString& theme);

} // namespace kimbim
