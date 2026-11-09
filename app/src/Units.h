// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// Length units for display and input. The model is in metres; the project chooses the unit people
// see and type (D108). Typed values may be sums and products ("3.6/2", "1200+150"), carry their own
// unit ("3600mm", "12'"), or be feet and inches ("5'6\"", "5'-6 1/2\"").

#include <QDoubleSpinBox>
#include <QObject>
#include <QString>

#include <optional>

namespace kimbim {

namespace units {

// Metres in one `unit` ("m", "cm", "mm", "ft", "in"; also "'" and "\""). 0 for an unknown unit.
double metresPer(const QString& unit);

// The project's unit and decimals, set when the project settings load; LengthSpinBoxes follow.
void setProject(const QString& unit, int decimals);
QString projectUnit();
int projectDecimals();

// Typed text as a number in the default unit whose size is `metresPerUnit` (1 for metres, 0.001 for
// millimetres...). A plain number is already in that unit; a number with a unit is converted to it.
// Arithmetic: + - * / and parentheses; a comma is a decimal point. nullopt for anything else.
std::optional<double> evaluate(const QString& text, double metresPerUnit = 1.0);

// Sends `changed` when the project unit changes.
class Notifier : public QObject {
    Q_OBJECT
signals:
    void changed();
};
Notifier* notifier();

} // namespace units

// A length field: value() is always in metres; it shows and takes the project unit, and accepts
// anything units::evaluate does ("12'", "3600 mm", "2.4+0.15").
class LengthSpinBox : public QDoubleSpinBox {
    Q_OBJECT
public:
    explicit LengthSpinBox(QWidget* parent = nullptr);

    QString textFromValue(double metres) const override;
    double valueFromText(const QString& text) const override;
    QValidator::State validate(QString& text, int& pos) const override;
    void fixup(QString& text) const override;
};

// QInputDialog::getDouble for a length: a LengthSpinBox in a small dialog. Returns metres; `ok` is
// false when cancelled (the value is then `metres`).
double askLength(QWidget* parent, const QString& title, const QString& label, double metres, double min,
    double max, bool* ok);

} // namespace kimbim
