// SPDX-License-Identifier: GPL-3.0-or-later
#include "Units.h"

#include <QDialog>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace units {

namespace {

QString s_unit = QStringLiteral("m");
int s_decimals = 2;

// A parsed value: in metres when it carried a unit, else a plain number in the default unit.
struct Q {
    double v = 0.0;
    bool length = false;
};

class Parser {
public:
    Parser(const QString& text, double mpu)
        : m_s(text)
        , m_mpu(mpu)
    {
        m_s.replace(QChar(0x2032), QLatin1Char('\'')); // prime and double prime
        m_s.replace(QChar(0x2033), QLatin1Char('"'));
        m_s.replace(QChar(0x2019), QLatin1Char('\''));
        m_s.replace(QChar(0x201D), QLatin1Char('"'));
        m_s.replace(QChar(0x2212), QLatin1Char('-')); // minus sign
    }

    std::optional<double> run()
    {
        std::optional<Q> q = expr();
        skip();
        if (!q || m_i != m_s.size() || !std::isfinite(q->v))
            return std::nullopt;
        return q->length ? q->v / m_mpu : q->v;
    }

private:
    QChar at(int k = 0) const { return m_i + k < m_s.size() ? m_s.at(m_i + k) : QChar(); }
    void skip()
    {
        while (at().isSpace())
            ++m_i;
    }
    double metres(const Q& q) const { return q.length ? q.v : q.v * m_mpu; }

    std::optional<Q> expr()
    {
        std::optional<Q> a = term();
        while (a) {
            skip();
            const QChar op = at();
            if (op != QLatin1Char('+') && op != QLatin1Char('-'))
                break;
            ++m_i;
            std::optional<Q> b = term();
            if (!b)
                return std::nullopt;
            const bool length = a->length || b->length;
            const double v = length ? metres(*a) + (op == QLatin1Char('+') ? 1 : -1) * metres(*b)
                                    : a->v + (op == QLatin1Char('+') ? 1 : -1) * b->v;
            a = Q{v, length};
        }
        return a;
    }

    std::optional<Q> term()
    {
        std::optional<Q> a = unary();
        while (a) {
            skip();
            const QChar op = at();
            if (op != QLatin1Char('*') && op != QLatin1Char('/') && op != QChar(0x00D7))
                break;
            ++m_i;
            std::optional<Q> b = unary();
            if (!b)
                return std::nullopt;
            if (op == QLatin1Char('/')) {
                if (b->v == 0.0 || (b->length && !a->length))
                    return std::nullopt;
                a = (a->length && b->length) ? Q{a->v / b->v, false} : Q{a->v / b->v, a->length};
            } else {
                if (a->length && b->length)
                    return std::nullopt; // an area is not a length
                a = Q{a->v * b->v, a->length || b->length};
            }
        }
        return a;
    }

    std::optional<Q> unary()
    {
        skip();
        if (at() == QLatin1Char('-') || at() == QLatin1Char('+')) {
            const bool minus = at() == QLatin1Char('-');
            ++m_i;
            std::optional<Q> q = unary();
            if (q && minus)
                q->v = -q->v;
            return q;
        }
        return juxtaposed();
    }

    // Feet then inches side by side add up: 5' 6", 5'6", 5'-6 1/2".
    std::optional<Q> juxtaposed()
    {
        std::optional<Q> a = quantity();
        if (!a || !a->length || !m_lastFeet)
            return a;
        const int save = m_i;
        skip();
        if (at() == QLatin1Char('-'))
            ++m_i;
        skip();
        if (at().isDigit() || at() == QLatin1Char('.')) {
            const std::optional<Q> b = quantity();
            if (b && b->length && m_lastInches)
                return Q{a->v + b->v, true};
            if (b && !b->length) // 5' 6: the second number is inches
                return Q{a->v + b->v * 0.0254, true};
        }
        m_i = save;
        return a;
    }

    std::optional<double> number()
    {
        const int start = m_i;
        while (at().isDigit() || at() == QLatin1Char('.') || at() == QLatin1Char(','))
            ++m_i;
        if (m_i == start)
            return std::nullopt;
        QString t = m_s.mid(start, m_i - start);
        t.replace(QLatin1Char(','), QLatin1Char('.'));
        bool ok = false;
        const double v = t.toDouble(&ok);
        if (!ok)
            return std::nullopt;
        // A mixed number: "6 1/2" (digits, a slash, digits, after a space).
        const int save = m_i;
        if (at().isSpace()) {
            skip();
            const int f = m_i;
            while (at().isDigit())
                ++m_i;
            if (m_i > f && at() == QLatin1Char('/')) {
                const double num = m_s.mid(f, m_i - f).toDouble();
                ++m_i;
                const int g = m_i;
                while (at().isDigit())
                    ++m_i;
                const double den = m_s.mid(g, m_i - g).toDouble();
                if (m_i > g && den != 0.0 && !at().isDigit())
                    return v + num / den;
            }
            m_i = save;
        }
        return v;
    }

    std::optional<Q> quantity()
    {
        skip();
        m_lastFeet = m_lastInches = false;
        Q q;
        if (at() == QLatin1Char('(')) {
            ++m_i;
            std::optional<Q> inner = expr();
            skip();
            if (!inner || at() != QLatin1Char(')'))
                return std::nullopt;
            ++m_i;
            q = *inner;
        } else {
            const std::optional<double> n = number();
            if (!n)
                return std::nullopt;
            q = Q{*n, false};
        }
        // a unit right after (spaces allowed)
        const int save = m_i;
        skip();
        QString unit;
        if (at() == QLatin1Char('\'') || at() == QLatin1Char('"')) {
            unit = at();
            ++m_i;
        } else {
            const int start = m_i;
            while (at().isLetter())
                ++m_i;
            unit = m_s.mid(start, m_i - start).toLower();
        }
        if (unit.isEmpty()) {
            m_i = save;
            return q;
        }
        const double mpu = metresPer(unit);
        if (mpu <= 0.0 || q.length)
            return std::nullopt;
        m_lastFeet = mpu == 0.3048;
        m_lastInches = mpu == 0.0254;
        return Q{q.v * mpu, true};
    }

    QString m_s;
    double m_mpu;
    int m_i = 0;
    bool m_lastFeet = false;
    bool m_lastInches = false;
};

} // namespace

double metresPer(const QString& unit)
{
    const QString u = unit.trimmed().toLower();
    if (u == QLatin1String("m") || u == QLatin1String("metre") || u == QLatin1String("metres")
        || u == QLatin1String("meter") || u == QLatin1String("meters"))
        return 1.0;
    if (u == QLatin1String("cm"))
        return 0.01;
    if (u == QLatin1String("mm"))
        return 0.001;
    if (u == QLatin1String("ft") || u == QLatin1String("'") || u == QLatin1String("feet") || u == QLatin1String("foot"))
        return 0.3048;
    if (u == QLatin1String("in") || u == QLatin1String("\"") || u == QLatin1String("inch") || u == QLatin1String("inches"))
        return 0.0254;
    return 0.0;
}

void setProject(const QString& unit, int decimals)
{
    const QString u = metresPer(unit) > 0 ? unit : QStringLiteral("m");
    if (u == s_unit && decimals == s_decimals)
        return;
    s_unit = u;
    s_decimals = std::clamp(decimals, 0, 6);
    emit notifier()->changed();
}

QString projectUnit() { return s_unit; }
int projectDecimals() { return s_decimals; }

std::optional<double> evaluate(const QString& text, double metresPerUnit)
{
    if (text.trimmed().isEmpty() || metresPerUnit <= 0.0)
        return std::nullopt;
    return Parser(text, metresPerUnit).run();
}

Notifier* notifier()
{
    static Notifier n;
    return &n;
}

} // namespace units

LengthSpinBox::LengthSpinBox(QWidget* parent)
    : QDoubleSpinBox(parent)
{
    setDecimals(6); // the value is in metres; what shows follows the project's decimals
    setKeyboardTracking(false);
    setCorrectionMode(QAbstractSpinBox::CorrectToPreviousValue);
    connect(units::notifier(), &units::Notifier::changed, this, [this] { lineEdit()->setText(textFromValue(value())); });
}

QString LengthSpinBox::textFromValue(double metres) const
{
    const QString unit = units::projectUnit();
    return QLocale().toString(metres / units::metresPer(unit), 'f', units::projectDecimals()) + QLatin1Char(' ') + unit;
}

double LengthSpinBox::valueFromText(const QString& text) const
{
    const double mpu = units::metresPer(units::projectUnit());
    QString t = text;
    t.remove(QLocale().groupSeparator());
    return units::evaluate(t, mpu).value_or(value() / mpu) * mpu;
}

QValidator::State LengthSpinBox::validate(QString& text, int& pos) const
{
    Q_UNUSED(pos);
    QString t = text;
    t.remove(QLocale().groupSeparator());
    const std::optional<double> v = units::evaluate(t, units::metresPer(units::projectUnit()));
    if (!v)
        return QValidator::Intermediate; // still typing ("5'", "3+")
    const double m = *v * units::metresPer(units::projectUnit());
    return (m >= minimum() - 1e-9 && m <= maximum() + 1e-9) ? QValidator::Acceptable : QValidator::Intermediate;
}

void LengthSpinBox::fixup(QString& text) const
{
    text = textFromValue(value());
}

double askLength(QWidget* parent, const QString& title, const QString& label, double metres, double min,
    double max, bool* ok)
{
    QDialog dialog(parent);
    dialog.setWindowTitle(title);
    auto* form = new QFormLayout(&dialog);
    auto* text = new QLabel(label, &dialog);
    text->setWordWrap(true);
    form->addRow(text);
    auto* box = new LengthSpinBox(&dialog);
    box->setObjectName(QStringLiteral("askLengthBox"));
    box->setRange(min, max);
    box->setValue(metres);
    box->selectAll();
    form->addRow(box);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    form->addRow(buttons);
    const bool accepted = dialog.exec() == QDialog::Accepted;
    if (ok)
        *ok = accepted;
    if (!accepted)
        return metres;
    box->interpretText();
    return box->value();
}

} // namespace kimbim
