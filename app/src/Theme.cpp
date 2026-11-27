// SPDX-License-Identifier: GPL-3.0-or-later
#include "Theme.h"

#include <QApplication>
#include <QGuiApplication>
#include <QPalette>
#include <QStyle>
#include <QStyleFactory>
#include <QStyleHints>

namespace kimbim {

namespace {
bool systemIsDark()
{
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
    return QGuiApplication::styleHints()->colorScheme() == Qt::ColorScheme::Dark;
#else
    return QApplication::palette().color(QPalette::Window).lightness() < 128;
#endif
}

QPalette darkPalette()
{
    QPalette p;
    const QColor window(43, 47, 51);
    const QColor base(35, 39, 43);
    const QColor alt(48, 53, 58);
    const QColor text(232, 234, 236);
    const QColor muted(166, 172, 178);
    const QColor button(53, 58, 64);
    const QColor highlight(61, 110, 168);
    p.setColor(QPalette::Window, window);
    p.setColor(QPalette::WindowText, text);
    p.setColor(QPalette::Base, base);
    p.setColor(QPalette::AlternateBase, alt);
    p.setColor(QPalette::ToolTipBase, alt);
    p.setColor(QPalette::ToolTipText, text);
    p.setColor(QPalette::Text, text);
    p.setColor(QPalette::Button, button);
    p.setColor(QPalette::ButtonText, text);
    p.setColor(QPalette::BrightText, Qt::white);
    p.setColor(QPalette::Link, QColor(126, 176, 232));
    p.setColor(QPalette::LinkVisited, QColor(178, 156, 224));
    p.setColor(QPalette::Highlight, highlight);
    p.setColor(QPalette::HighlightedText, Qt::white);
    p.setColor(QPalette::PlaceholderText, muted);
    p.setColor(QPalette::Light, QColor(72, 78, 85));
    p.setColor(QPalette::Midlight, QColor(61, 67, 73));
    p.setColor(QPalette::Mid, QColor(35, 39, 43));
    p.setColor(QPalette::Dark, QColor(24, 27, 30));
    p.setColor(QPalette::Shadow, QColor(14, 16, 18));
    p.setColor(QPalette::Disabled, QPalette::Text, muted);
    p.setColor(QPalette::Disabled, QPalette::WindowText, muted);
    p.setColor(QPalette::Disabled, QPalette::ButtonText, muted);
    p.setColor(QPalette::Disabled, QPalette::Highlight, QColor(78, 84, 90));
    p.setColor(QPalette::Disabled, QPalette::HighlightedText, muted);
    return p;
}
} // namespace

void applyTheme(const QString& theme)
{
    const QString key = theme.trimmed().toLower();
    const bool dark = key == QLatin1String("dark")
        || (key != QLatin1String("light") && systemIsDark());
    if (QStyle* fusion = QStyleFactory::create(QStringLiteral("Fusion")))
        QApplication::setStyle(fusion);
    if (dark)
        QApplication::setPalette(darkPalette());
    else
        QApplication::setPalette(QApplication::style()->standardPalette());
}

} // namespace kimbim
