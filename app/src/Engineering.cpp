// SPDX-License-Identifier: GPL-3.0-or-later
// D248: the Engineering menu - MEP systems and terminals, HVAC/water/drainage sizing, electrical
// circuits and panel schedules, structural analysis and its utilisation colours, and the
// engineering settings. The calculations live in Python (mep, hvac, plumbing, drainage,
// electrical, structanalysis); this file only asks for inputs and shows the reports.

#include "LevelsBar.h"
#include "MainWindow.h"
#include "StatusStrip.h"
#include "Units.h"
#include "Viewport.h"
#include <QAction>
#include <QComboBox>
#include <QCoreApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QColor>
#include <QHash>
#include <QHeaderView>
#include <QLocale>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMenuBar>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>
#include <functional>

namespace kimbim {

namespace {

// Labels and statuses that come from Python (mep.CATALOGUE, mep.SYSTEM_KINDS, the sizing reports):
// listed here so lupdate offers them for translation; shown through dyn().
[[maybe_unused]] const char* const kDynamicStrings[] = {
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Supply air"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Return air"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Exhaust air"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Outside air"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Domestic cold water"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Domestic hot water"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Sanitary drainage"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Storm water"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Vent"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Data"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Supply diffuser"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Return grille"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Exhaust valve"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Air handling unit"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Fan"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "WC"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Wash basin"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Kitchen sink"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Shower"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Bath"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Urinal"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Washing machine"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Dishwasher"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Floor drain"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Roof drain"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Drain outlet (to sewer)"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Water main / meter"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Water heater"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Pump"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Distribution board"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Socket outlet"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Light fixture"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "Switch"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "Electric appliance"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "ok"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "pass"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "warn"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "fail"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "no flow"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "low pressure"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "largest size exceeded"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "largest stack exceeded"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "falls the wrong way"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "voltage drop over the limit"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "load above the largest breaker"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "main"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "branch"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "terminal"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "power"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "lighting"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "column"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "beam"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "member"),
    QT_TRANSLATE_NOOP("kimbim::MainWindow", "yes"), QT_TRANSLATE_NOOP("kimbim::MainWindow", "stack"),
};

QString dyn(const QString& text)
{
    return QCoreApplication::translate("kimbim::MainWindow", text.toUtf8().constData());
}

QString compact(const QJsonValue& v)
{
    if (v.isObject())
        return QString::fromUtf8(QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
    return QString::fromUtf8(QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
}

QString number(const QJsonValue& v, int decimals)
{
    if (v.isDouble())
        return QString::number(v.toDouble(), 'f', decimals);
    if (v.isBool())
        return v.toBool() ? dyn(QStringLiteral("yes")) : QString();
    return v.toString();
}

// One column of a report table: a header and how to read the row.
struct Column {
    QString header;
    std::function<QString(const QJsonObject&)> text;
};

Column field(const QString& header, const char* key, int decimals = 2, double scale = 1.0)
{
    return {header, [key, decimals, scale](const QJsonObject& row) {
                const QJsonValue v = row.value(QLatin1String(key));
                if (v.isDouble() && scale != 1.0)
                    return QString::number(v.toDouble() * scale, 'f', decimals);
                return number(v, decimals);
            }};
}

bool failing(const QJsonObject& row)
{
    const QString status = row.value("status").toString();
    return !status.isEmpty() && status != QLatin1String("ok") && status != QLatin1String("pass")
        && status != QLatin1String("no flow");
}

// Flattens a settings table into "a.b.c" = value rows (lists stay one leaf).
void flatten(const QJsonObject& o, const QString& prefix, QList<QPair<QString, QJsonValue>>& out)
{
    for (auto it = o.begin(); it != o.end(); ++it) {
        const QString path = prefix.isEmpty() ? it.key() : prefix + QLatin1Char('.') + it.key();
        if (it.value().isObject() && !it.value().toObject().isEmpty())
            flatten(it.value().toObject(), path, out);
        else
            out.append({path, it.value()});
    }
}

void setPath(QJsonObject& root, const QStringList& parts, const QJsonValue& v)
{
    if (parts.size() == 1) {
        root.insert(parts.first(), v);
        return;
    }
    QJsonObject child = root.value(parts.first()).toObject();
    setPath(child, parts.mid(1), v);
    root.insert(parts.first(), child);
}

} // namespace

void MainWindow::buildEngineeringMenu()
{
    if (!m_menuBar)
        return;
    QAction* modelMenu = nullptr;
    QAction* after = nullptr;
    const QList<QAction*> tops = m_menuBar->actions();
    for (int i = 0; i < tops.size(); ++i)
        if (tops[i]->menu() && tops[i]->menu()->title() == tr("&Model")) {
            modelMenu = tops[i];
            after = i + 1 < tops.size() ? tops[i + 1] : nullptr;
        }
    auto* menu = new QMenu(tr("&Engineering"), this);
    menu->setObjectName(QStringLiteral("engineeringMenu"));
    if (after)
        m_menuBar->insertMenu(after, menu);
    else
        m_menuBar->addMenu(menu);
    Q_UNUSED(modelMenu);
    auto add = [this](QMenu* to, const QString& text, const char* name, const QString& tip, auto slot) {
        QAction* a = to->addAction(text);
        a->setObjectName(QLatin1String(name));
        a->setToolTip(tip);
        connect(a, &QAction::triggered, this, slot);
        return a;
    };
    auto moveHere = [this](QMenu* to, const char* name) {
        if (QAction* a = findChild<QAction*>(QLatin1String(name))) {
            for (QObject* o : a->associatedObjects())
                if (auto* m = qobject_cast<QMenu*>(o); m && m != to)
                    m->removeAction(a);
            to->addAction(a);
        }
    };

    // MEP: systems, terminals, runs and connections
    QMenu* mepMenu = menu->addMenu(tr("&MEP"));
    mepMenu->setObjectName(QStringLiteral("engineeringMenuMep"));
    add(mepMenu, tr("MEP &systems..."), "actionMepSystems",
        tr("Distribution systems: their kind, elements and open ports; new systems and assigning the selection"),
        [this] { mepSystemsDialog(); });
    add(mepMenu, tr("Place &terminal or equipment..."), "actionPlaceMepTerminal",
        tr("Diffusers, grilles, air handlers, fixtures, drains, boards, sockets, lights... with their ports"),
        [this] { placeMepTerminalCommand(); });
    for (const char* name : {"actionDuct", "actionPipe", "actionCableTray"})
        moveHere(mepMenu, name);
    add(mepMenu, tr("&Drain run..."), "actionDrainRun", tr("A drain pipe through clicked points falling at a slope"),
        [this] { drainRunCommand(); });
    add(mepMenu, tr("&Connect touching ports"), "actionConnectNetwork",
        tr("Join every pair of free MEP ports that touch"), [this] {
            const QJsonObject r = bridge("connect_network", {QString()});
            if (!r.value("ok").toBool())
                return showError(tr("Connect touching ports"), r.value("error").toString());
            afterEdit(r);
            m_status->showMessage(tr("%n connection(s) made", nullptr, r.value("connected").toInt()));
        });

    // calculations
    QMenu* hvacMenu = menu->addMenu(tr("&HVAC"));
    hvacMenu->setObjectName(QStringLiteral("engineeringMenuHvac"));
    add(hvacMenu, tr("&Airflow and duct sizing..."), "actionAirflowSizing",
        tr("Room airflows, duct sizes by equal friction and velocity, pressure drop and the fan duty"),
        [this] { engineeringCalcDialog(QStringLiteral("air")); });
    QMenu* plumbingMenu = menu->addMenu(tr("&Plumbing"));
    plumbingMenu->setObjectName(QStringLiteral("engineeringMenuPlumbing"));
    add(plumbingMenu, tr("&Water supply sizing..."), "actionWaterSizing",
        tr("Peak flows, pipe sizes and the pressure left at each fixture"),
        [this] { engineeringCalcDialog(QStringLiteral("water")); });
    add(plumbingMenu, tr("&Drainage sizing..."), "actionDrainageSizing",
        tr("Sanitary and storm flows, pipe and stack sizes, slope checks"),
        [this] { engineeringCalcDialog(QStringLiteral("drainage")); });
    QMenu* electricalMenu = menu->addMenu(tr("E&lectrical"));
    electricalMenu->setObjectName(QStringLiteral("engineeringMenuElectrical"));
    add(electricalMenu, tr("&Circuit from selection..."), "actionCreateCircuit",
        tr("A circuit from a distribution board to the selected devices"), [this] { circuitFromSelection(); });
    add(electricalMenu, tr("&Panel schedule..."), "actionPanelSchedule",
        tr("A board's circuits with breakers, cables, voltage drop and phase loads"),
        [this] { engineeringCalcDialog(QStringLiteral("panel")); });
    QMenu* structureMenu = menu->addMenu(tr("&Structure"));
    structureMenu->setObjectName(QStringLiteral("engineeringMenuStructure"));
    moveHere(structureMenu, "actionAnalyticalModel");
    add(structureMenu, tr("&Analyse structure..."), "actionAnalyseStructure",
        tr("Loads from the model, a frame analysis and member checks (utilisation and deflection)"),
        [this] { engineeringCalcDialog(QStringLiteral("structure")); });
    QAction* colours = add(structureMenu, tr("Show &utilisation"), "actionShowUtilisation",
        tr("Colour the analysed members green, amber or red by their utilisation"), [this](bool on) {
            if (!m_viewport)
                return;
            if (!on) {
                m_viewport->setElementColors({});
                return;
            }
            const QJsonObject r = bridge("utilisation_colours");
            QHash<QString, QColor> map;
            const QJsonObject c = r.value("colours").toObject();
            for (auto it = c.begin(); it != c.end(); ++it)
                map.insert(it.key(), QColor(it.value().toString()));
            m_viewport->setElementColors(map);
            m_status->showMessage(map.isEmpty() ? tr("No structural results yet: run Analyse structure first")
                                                : tr("%n member(s) coloured by utilisation", nullptr, int(map.size())));
        });
    colours->setCheckable(true);
    menu->addSeparator();
    add(menu, tr("Engineering &settings..."), "actionEngineeringSettings",
        tr("Codes, limits and tables behind the MEP and structural calculations"),
        [this] { engineeringSettingsDialog(); });
}

void MainWindow::mepSystemsDialog()
{
    QDialog dialog(this);
    dialog.setWindowTitle(tr("MEP systems"));
    dialog.resize(720, 420);
    auto* layout = new QVBoxLayout(&dialog);
    auto* table = new QTableWidget(&dialog);
    table->setObjectName(QStringLiteral("mepSystemsTable"));
    table->setColumnCount(4);
    table->setHorizontalHeaderLabels({tr("System"), tr("Kind"), tr("Elements"), tr("Open ports")});
    table->horizontalHeader()->setStretchLastSection(true);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    layout->addWidget(table, 1);
    auto* notes = new QLabel(&dialog);
    notes->setWordWrap(true);
    layout->addWidget(notes);
    const QJsonArray kinds = bridge("mep_catalogue").value("system_kinds").toArray();
    auto refresh = [&] {
        const QJsonArray systems = bridge("mep_systems").value("systems").toArray();
        table->setRowCount(systems.size());
        for (int i = 0; i < systems.size(); ++i) {
            const QJsonObject s = systems[i].toObject();
            auto* name = new QTableWidgetItem(s.value("name").toString());
            name->setData(Qt::UserRole, s.value("guid").toString());
            name->setForeground(QColor(s.value("colour").toString()));
            table->setItem(i, 0, name);
            table->setItem(i, 1, new QTableWidgetItem(dyn(s.value("label").toString())));
            table->setItem(i, 2, new QTableWidgetItem(QString::number(s.value("count").toInt())));
            table->setItem(i, 3, new QTableWidgetItem(QString::number(s.value("open_ports").toInt())));
        }
    };
    auto current = [&]() -> QString {
        const int row = table->currentRow();
        return row >= 0 && table->item(row, 0) ? table->item(row, 0)->data(Qt::UserRole).toString() : QString();
    };
    auto* buttons = new QHBoxLayout;
    layout->addLayout(buttons);
    auto button = [&](const QString& text) {
        auto* b = new QPushButton(text, &dialog);
        buttons->addWidget(b);
        return b;
    };
    connect(button(tr("New system...")), &QPushButton::clicked, &dialog, [&] {
        QDialog ask(&dialog);
        ask.setWindowTitle(tr("New system"));
        auto* form = new QFormLayout(&ask);
        auto* name = new QLineEdit(&ask);
        auto* kind = new QComboBox(&ask);
        for (const auto& k : kinds)
            kind->addItem(dyn(k.toObject().value("label").toString()), k.toObject().value("kind").toString());
        form->addRow(tr("Name:"), name);
        form->addRow(tr("Kind:"), kind);
        auto* ok = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &ask);
        form->addRow(ok);
        connect(ok, &QDialogButtonBox::accepted, &ask, &QDialog::accept);
        connect(ok, &QDialogButtonBox::rejected, &ask, &QDialog::reject);
        if (ask.exec() != QDialog::Accepted)
            return;
        const QJsonObject r = bridge("create_mep_system", {name->text().trimmed(), kind->currentData().toString()});
        if (!r.value("ok").toBool())
            return showError(tr("New system"), r.value("error").toString());
        afterEdit(r);
        refresh();
    });
    connect(button(tr("Assign selection")), &QPushButton::clicked, &dialog, [&] {
        if (current().isEmpty() || m_selection.isEmpty())
            return showError(tr("MEP systems"), tr("Select a system here and elements in the model"));
        const QJsonObject r = bridge("assign_to_system", {compact(QJsonArray::fromStringList(m_selection)), current()});
        if (!r.value("ok").toBool())
            return showError(tr("MEP systems"), r.value("error").toString());
        afterEdit(r);
        refresh();
    });
    connect(button(tr("Connect")), &QPushButton::clicked, &dialog, [&] {
        const QJsonObject r = bridge("connect_network", {current()});
        if (!r.value("ok").toBool())
            return showError(tr("MEP systems"), r.value("error").toString());
        afterEdit(r);
        refresh();
        notes->setText(tr("%n connection(s) made", nullptr, r.value("connected").toInt()));
    });
    connect(button(tr("Check network")), &QPushButton::clicked, &dialog, [&] {
        if (current().isEmpty())
            return;
        const QJsonObject r = bridge("mep_network", {current()});
        if (!r.value("ok").toBool())
            return showError(tr("MEP systems"), r.value("error").toString());
        QStringList lines;
        for (const auto& v : r.value("issues").toArray())
            lines << dyn(v.toString());
        notes->setText(lines.isEmpty() ? tr("The network is connected from its source to every element")
                                       : lines.join(QLatin1Char('\n')));
        QStringList select;
        for (const auto& v : r.value("unreached").toArray())
            select << v.toString();
        if (!select.isEmpty())
            setSelection(select);
    });
    connect(button(tr("Select elements")), &QPushButton::clicked, &dialog, [&] {
        const QJsonObject r = bridge("mep_network", {current()});
        QStringList select;
        for (const auto& v : r.value("elements").toArray())
            select << v.toObject().value("guid").toString();
        setSelection(select);
    });
    connect(button(tr("Delete")), &QPushButton::clicked, &dialog, [&] {
        if (current().isEmpty())
            return;
        const QJsonObject r = bridge("remove_mep_system", {current()});
        if (!r.value("ok").toBool())
            return showError(tr("MEP systems"), r.value("error").toString());
        afterEdit(r);
        refresh();
    });
    buttons->addStretch(1);
    auto* close = button(tr("Close"));
    connect(close, &QPushButton::clicked, &dialog, &QDialog::accept);
    refresh();
    dialog.exec();
}

void MainWindow::placeMepTerminalCommand()
{
    const QJsonArray kinds = bridge("mep_catalogue").value("kinds").toArray();
    if (kinds.isEmpty())
        return;
    QString kind = kinds.first().toObject().value("kind").toString();
    QString system;
    double rotation = 0.0;
    QString height; // blank: the catalogue height
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Place terminal or equipment"));
        auto* form = new QFormLayout(&dialog);
        auto* what = new QComboBox(&dialog);
        for (const auto& k : kinds) {
            const QJsonObject o = k.toObject();
            what->addItem(dyn(o.value("label").toString()), o.value("kind").toString());
        }
        auto* sys = new QComboBox(&dialog);
        sys->addItem(tr("(none)"), QString());
        for (const auto& v : bridge("mep_systems").value("systems").toArray())
            sys->addItem(v.toObject().value("name").toString(), v.toObject().value("guid").toString());
        auto* z = new LengthSpinBox(&dialog);
        z->setRange(-20.0, 50.0);
        auto setDefaultZ = [&] {
            for (const auto& k : kinds)
                if (k.toObject().value("kind").toString() == what->currentData().toString())
                    z->setValue(k.toObject().value("z").toDouble());
        };
        setDefaultZ();
        connect(what, &QComboBox::currentIndexChanged, &dialog, setDefaultZ);
        auto* turn = new QDoubleSpinBox(&dialog);
        turn->setRange(-360.0, 360.0);
        turn->setSuffix(QStringLiteral("°"));
        form->addRow(tr("Kind:"), what);
        form->addRow(tr("System:"), sys);
        form->addRow(tr("Base above the level:"), z);
        form->addRow(tr("Rotation:"), turn);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        kind = what->currentData().toString();
        system = sys->currentData().toString();
        rotation = turn->value();
        height = QString::number(z->value(), 'g', 17);
    }
    pickPoints(1, false, {tr("Click where it goes")},
        [this, kind, system, rotation, height](const QVector<QPointF>& p, const QString&) {
            const QJsonObject r = bridge("place_mep_terminal", {kind, m_levels->activeStorey(),
                QString::number(p.first().x(), 'g', 17), QString::number(p.first().y(), 'g', 17), height,
                QString::number(rotation, 'g', 17), system});
            if (!r.value("ok").toBool())
                return showError(tr("Place terminal or equipment"), r.value("error").toString());
            m_pendingLabel = tr("Place terminal");
            afterEdit(r);
            m_pendingLabel.clear();
        });
}

void MainWindow::drainRunCommand()
{
    double diameter = 0.11, start = -0.1, slope = 0.0;
    QString system;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Drain run"));
        auto* form = new QFormLayout(&dialog);
        auto* d = new LengthSpinBox(&dialog);
        d->setRange(0.02, 1.0);
        d->setValue(diameter);
        auto* z = new LengthSpinBox(&dialog);
        z->setRange(-20.0, 50.0);
        z->setValue(start);
        auto* s = new QDoubleSpinBox(&dialog);
        s->setRange(0.0, 50.0);
        s->setDecimals(2);
        s->setSuffix(QStringLiteral(" %"));
        s->setSpecialValueText(tr("Default"));
        auto* sys = new QComboBox(&dialog);
        sys->setEditable(true);
        for (const auto& v : bridge("mep_systems").value("systems").toArray())
            if (v.toObject().value("domain").toString() == QLatin1String("drainage"))
                sys->addItem(v.toObject().value("name").toString());
        form->addRow(tr("Diameter:"), d);
        form->addRow(tr("Start height above the level:"), z);
        form->addRow(tr("Slope:"), s);
        form->addRow(tr("System:"), sys);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        diameter = d->value();
        start = z->value();
        slope = s->value() / 100.0;
        system = sys->currentText().trimmed();
    }
    pickPoints(-2, false, {tr("Click where the drain starts (its high end)"),
                              tr("Click the next point downhill; Enter finishes, Esc cancels")},
        [this, diameter, start, slope, system](const QVector<QPointF>& p, const QString&) {
            QJsonArray points;
            for (const QPointF& q : p)
                points.append(QJsonArray{q.x(), q.y()});
            const QJsonObject r = bridge("create_drain_run", {m_levels->activeStorey(), compact(points),
                QString::number(start, 'g', 17), slope > 0 ? QString::number(slope, 'g', 17) : QString(),
                QString::number(diameter, 'g', 17), system});
            if (!r.value("ok").toBool())
                return showError(tr("Drain run"), r.value("error").toString());
            m_pendingLabel = tr("Drain run");
            afterEdit(r);
            m_pendingLabel.clear();
        });
}

void MainWindow::circuitFromSelection()
{
    const QJsonObject listed = bridge("circuits", {QString()});
    const QJsonArray boards = listed.value("boards").toArray();
    if (boards.isEmpty())
        return showError(tr("Circuit from selection"), tr("Place a distribution board first (MEP > Place terminal or equipment)"));
    if (m_selection.isEmpty())
        return showError(tr("Circuit from selection"), tr("Select the sockets, lights or appliances the circuit feeds"));
    QString board = boards.first().toObject().value("guid").toString();
    QString name, phase = QStringLiteral("auto"), kind;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Circuit from selection"));
        auto* form = new QFormLayout(&dialog);
        auto* b = new QComboBox(&dialog);
        for (const auto& v : boards)
            b->addItem(v.toObject().value("name").toString(), v.toObject().value("guid").toString());
        auto* n = new QLineEdit(&dialog);
        n->setPlaceholderText(tr("Automatic"));
        auto* ph = new QComboBox(&dialog);
        ph->addItem(tr("Balance automatically"), QStringLiteral("auto"));
        for (const char* p : {"L1", "L2", "L3"})
            ph->addItem(QLatin1String(p), QLatin1String(p));
        ph->addItem(tr("Three-phase"), QStringLiteral("3P"));
        auto* k = new QComboBox(&dialog);
        k->addItem(tr("From the devices"), QString());
        k->addItem(tr("Power"), QStringLiteral("power"));
        k->addItem(tr("Lighting"), QStringLiteral("lighting"));
        form->addRow(tr("Board:"), b);
        form->addRow(tr("Name:"), n);
        form->addRow(tr("Phase:"), ph);
        form->addRow(tr("Kind:"), k);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        board = b->currentData().toString();
        name = n->text().trimmed();
        phase = ph->currentData().toString();
        kind = k->currentData().toString();
    }
    const QJsonObject r = bridge("create_circuit", {board, compact(QJsonArray::fromStringList(m_selection)), name, phase, kind});
    if (!r.value("ok").toBool())
        return showError(tr("Circuit from selection"), r.value("error").toString());
    afterEdit(r);
    m_status->showMessage(tr("Circuit %1 made").arg(r.value("name").toString()));
}

void MainWindow::engineeringCalcDialog(const QString& kind)
{
    // what each calculation reads and shows
    QString title, function, rowsKey, domain;
    QList<Column> columns;
    const Column size{tr("Size"), [](const QJsonObject& row) {
                          if (row.contains("dn"))
                              return QStringLiteral("DN %1").arg(row.value("dn").toInt());
                          if (row.contains("nominal"))
                              return QStringLiteral("%1 mm").arg(row.value("nominal").toString());
                          if (row.value("shape").toString() == QLatin1String("round"))
                              return QStringLiteral("Ø%1").arg(qRound(row.value("width").toDouble() * 1000));
                          return QStringLiteral("%1 × %2").arg(qRound(row.value("width").toDouble() * 1000))
                              .arg(qRound(row.value("height").toDouble() * 1000));
                      }};
    const Column status{tr("Status"), [](const QJsonObject& row) {
                            return dyn(row.value("status").toString());
                        }};
    if (kind == QLatin1String("air")) {
        title = tr("Airflow and duct sizing");
        function = QStringLiteral("size_air_system");
        rowsKey = QStringLiteral("segments");
        domain = QStringLiteral("air");
        columns = {field(tr("Duct"), "name"), {tr("Role"), [](const QJsonObject& row) { return dyn(row.value("role").toString()); }}, field(tr("Flow L/s"), "flow", 1), size,
            field(tr("Velocity m/s"), "velocity"), field(tr("Pa/m"), "gradient"), field(tr("Δp Pa"), "pressure_drop", 1),
            status};
    } else if (kind == QLatin1String("water")) {
        title = tr("Water supply sizing");
        function = QStringLiteral("size_water_system");
        rowsKey = QStringLiteral("segments");
        domain = QStringLiteral("water");
        columns = {field(tr("Pipe"), "name"), {tr("Role"), [](const QJsonObject& row) { return dyn(row.value("role").toString()); }}, field(tr("LU"), "loading_units", 1),
            field(tr("Peak L/s"), "flow", 3), size, field(tr("Velocity m/s"), "velocity"),
            field(tr("Δp Pa"), "pressure_drop", 0), status};
    } else if (kind == QLatin1String("drainage")) {
        title = tr("Drainage sizing");
        function = QStringLiteral("size_drainage_system");
        rowsKey = QStringLiteral("segments");
        domain = QStringLiteral("drainage");
        columns = {field(tr("Pipe"), "name"), field(tr("DU"), "discharge_units", 1), field(tr("Flow L/s"), "flow", 2),
            {tr("Slope %"), [](const QJsonObject& row) {
                 return row.value("vertical").toBool() ? dyn(QStringLiteral("stack"))
                                                       : QString::number(row.value("slope").toDouble() * 100, 'f', 2);
             }},
            size, field(tr("Capacity L/s"), "capacity", 2), status};
    } else if (kind == QLatin1String("panel")) {
        title = tr("Panel schedule");
        function = QStringLiteral("panel_schedule");
        rowsKey = QStringLiteral("circuits");
        columns = {field(tr("Circuit"), "name"), {tr("Kind"), [](const QJsonObject& row) { return dyn(row.value("kind").toString()); }},
            {tr("Phase"), [](const QJsonObject& row) {
                 return row.contains("phase_assigned") ? row.value("phase_assigned").toString() + QStringLiteral(" *")
                                                       : row.value("phase").toString();
             }},
            field(tr("Devices"), "devices", 0), field(tr("Demand VA"), "demand_va", 0), field(tr("Ib A"), "design_current"),
            field(tr("Breaker A"), "breaker", 0), field(tr("Cable mm²"), "cable", 1), field(tr("Length m"), "length", 1),
            field(tr("ΔU %"), "voltage_drop"), status};
    } else {
        title = tr("Structural analysis");
        function = QStringLiteral("analyse_structure");
        rowsKey = QStringLiteral("members");
        columns = {field(tr("Member"), "name"), {tr("Kind"), [](const QJsonObject& row) { return dyn(row.value("kind").toString()); }}, field(tr("Material"), "material"),
            field(tr("Utilisation"), "utilisation", 2), field(tr("Governing"), "governing"),
            field(tr("N kN"), "N_compression", 1), field(tr("My kNm"), "My", 1), field(tr("Deflection mm"), "deflection", 1, 1000.0),
            field(tr("Limit mm"), "deflection_limit", 1, 1000.0), status};
    }

    QDialog dialog(this);
    dialog.setWindowTitle(title);
    dialog.resize(980, 620);
    auto* layout = new QVBoxLayout(&dialog);
    auto* top = new QHBoxLayout;
    layout->addLayout(top);
    auto* target = new QComboBox(&dialog);
    target->setObjectName(QStringLiteral("engineeringTarget"));
    if (kind == QLatin1String("panel")) {
        top->addWidget(new QLabel(tr("Board:"), &dialog));
        for (const auto& v : bridge("circuits", {QString()}).value("boards").toArray())
            target->addItem(v.toObject().value("name").toString(), v.toObject().value("guid").toString());
        top->addWidget(target, 1);
    } else if (!domain.isEmpty()) {
        top->addWidget(new QLabel(tr("System:"), &dialog));
        for (const auto& v : bridge("mep_systems").value("systems").toArray())
            if (v.toObject().value("domain").toString() == domain)
                target->addItem(v.toObject().value("name").toString(), v.toObject().value("guid").toString());
        top->addWidget(target, 1);
    } else {
        target->hide();
        top->addStretch(1);
    }
    auto* calculate = new QPushButton(tr("Calculate"), &dialog);
    top->addWidget(calculate);
    auto* table = new QTableWidget(&dialog);
    table->setObjectName(QStringLiteral("engineeringTable"));
    table->setColumnCount(columns.size());
    QStringList headers;
    for (const Column& c : columns)
        headers << c.header;
    table->setHorizontalHeaderLabels(headers);
    table->horizontalHeader()->setStretchLastSection(true);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    layout->addWidget(table, 3);
    auto* summary = new QLabel(&dialog);
    summary->setWordWrap(true);
    layout->addWidget(summary);
    auto* notes = new QPlainTextEdit(&dialog);
    notes->setReadOnly(true);
    layout->addWidget(notes, 1);
    auto* buttons = new QHBoxLayout;
    layout->addLayout(buttons);
    auto* apply = new QPushButton(kind == QLatin1String("structure") ? tr("Save results to the model")
                                  : kind == QLatin1String("panel") ? tr("Apply breakers, cables and phases")
                                                                   : tr("Apply sizes"), &dialog);
    auto* selectFailing = new QPushButton(tr("Select failing"), &dialog);
    auto* close = new QPushButton(tr("Close"), &dialog);
    buttons->addWidget(apply);
    buttons->addWidget(selectFailing);
    buttons->addStretch(1);
    buttons->addWidget(close);
    QJsonObject report;

    auto run = [&](bool write) {
        QStringList args;
        if (!domain.isEmpty() || kind == QLatin1String("panel")) {
            if (target->currentData().toString().isEmpty()) {
                summary->setText(kind == QLatin1String("panel") ? tr("There is no distribution board")
                                                                : tr("There is no system of this kind"));
                return;
            }
            args << target->currentData().toString();
        }
        args << (write ? QStringLiteral("true") : QStringLiteral("false"));
        report = bridge(function.toUtf8().constData(), args);
        if (!report.value("ok").toBool()) {
            summary->setText(report.value("error").toString());
            table->setRowCount(0);
            QStringList lines;
            for (const auto& v : report.value("warnings").toArray())
                lines << v.toString();
            notes->setPlainText(lines.join(QLatin1Char('\n')));
            return;
        }
        if (write) {
            afterEdit(report);
            if (QAction* c = findChild<QAction*>(QStringLiteral("actionShowUtilisation")); c && c->isChecked())
                c->trigger(), c->trigger(); // refresh the colours
        }
        const QJsonArray rows = report.value(rowsKey).toArray();
        table->setRowCount(rows.size());
        for (int i = 0; i < rows.size(); ++i) {
            const QJsonObject row = rows[i].toObject();
            for (int c = 0; c < columns.size(); ++c) {
                auto* item = new QTableWidgetItem(columns[c].text(row));
                if (c == 0)
                    item->setData(Qt::UserRole, row.value("guid").toString());
                if (failing(row))
                    item->setForeground(QColor(200, 40, 40));
                else if (row.value("status").toString() == QLatin1String("warn"))
                    item->setForeground(QColor(190, 130, 0));
                table->setItem(i, c, item);
            }
        }
        table->resizeColumnsToContents();
        if (kind == QLatin1String("air"))
            summary->setText(tr("System flow %1 L/s; the fan must give %2 Pa at the critical terminal")
                                 .arg(report.value("system_flow").toDouble(), 0, 'f', 1)
                                 .arg(report.value("fan_pressure").toDouble(), 0, 'f', 0));
        else if (kind == QLatin1String("water"))
            summary->setText(tr("Peak flow %1 L/s; %2 kPa left at the critical fixture")
                                 .arg(report.value("peak_flow").toDouble(), 0, 'f', 2)
                                 .arg(report.value("critical_pressure_kpa").toDouble(), 0, 'f', 0));
        else if (kind == QLatin1String("drainage"))
            summary->setText(tr("%1 L/s at the outlet").arg(report.value("outlet_flow").toDouble(), 0, 'f', 2));
        else if (kind == QLatin1String("panel")) {
            const QJsonObject p = report.value("phase_loads").toObject();
            summary->setText(tr("Demand %1 VA (L1 %2, L2 %3, L3 %4); main breaker %5 A; imbalance %6 %")
                                 .arg(report.value("total_demand_va").toDouble(), 0, 'f', 0)
                                 .arg(p.value("L1").toDouble(), 0, 'f', 0).arg(p.value("L2").toDouble(), 0, 'f', 0)
                                 .arg(p.value("L3").toDouble(), 0, 'f', 0).arg(report.value("main_breaker").toDouble())
                                 .arg(report.value("imbalance").toDouble() * 100, 0, 'f', 0));
        } else {
            const QJsonObject n = report.value("counts").toObject();
            summary->setText(tr("Highest utilisation %1: %2 pass, %3 warn, %4 fail. Loads %5 kN = reactions %6 kN")
                                 .arg(report.value("max_utilisation").toDouble(), 0, 'f', 2)
                                 .arg(n.value("pass").toInt()).arg(n.value("warn").toInt()).arg(n.value("fail").toInt())
                                 .arg(report.value("total_uls_kN").toDouble(), 0, 'f', 1)
                                 .arg(report.value("total_reaction_kN").toDouble(), 0, 'f', 1));
        }
        QStringList lines;
        for (const auto& v : report.value("warnings").toArray())
            lines << QStringLiteral("⚠ ") + v.toString();
        if (kind == QLatin1String("structure")) {
            for (const auto& v : report.value("reactions").toArray()) {
                const QJsonObject r = v.toObject();
                const QJsonArray f = r.value("force").toArray();
                lines << tr("Support at %1, %2 (%3): Fz %4 kN")
                             .arg(r.value("point").toArray()[0].toDouble(), 0, 'f', 2)
                             .arg(r.value("point").toArray()[1].toDouble(), 0, 'f', 2)
                             .arg(r.value("kind").toString()).arg(f[2].toDouble(), 0, 'f', 1);
            }
            for (const auto& v : report.value("walls").toArray())
                lines << tr("Wall %1: %2 kN/m (ULS)").arg(v.toObject().value("name").toString())
                             .arg(v.toObject().value("uls_kN_per_m").toDouble(), 0, 'f', 1);
        }
        lines << QString() << tr("Method: %1").arg(report.value("method").toString());
        for (const auto& v : report.value("assumptions").toArray())
            lines << QStringLiteral("• ") + v.toString();
        notes->setPlainText(lines.join(QLatin1Char('\n')));
    };
    connect(calculate, &QPushButton::clicked, &dialog, [&] { run(false); });
    connect(target, &QComboBox::currentIndexChanged, &dialog, [&] { run(false); });
    connect(apply, &QPushButton::clicked, &dialog, [&] { run(true); });
    connect(selectFailing, &QPushButton::clicked, &dialog, [&] {
        QStringList select;
        for (const auto& v : report.value(rowsKey).toArray())
            if (failing(v.toObject()) || v.toObject().value("status").toString() == QLatin1String("warn"))
                select << v.toObject().value("guid").toString();
        setSelection(select);
    });
    connect(table, &QTableWidget::itemDoubleClicked, &dialog, [&](QTableWidgetItem* item) {
        if (QTableWidgetItem* first = table->item(item->row(), 0))
            setSelection({first->data(Qt::UserRole).toString()});
    });
    connect(close, &QPushButton::clicked, &dialog, &QDialog::accept);
    run(false);
    dialog.exec();
}

void MainWindow::engineeringSettingsDialog()
{
    struct Discipline {
        QString label;
        const char* key;
    };
    const QList<Discipline> disciplines{{tr("MEP network"), "mep_settings"}, {tr("HVAC"), "hvac_settings"},
        {tr("Water supply"), "plumbing_settings"}, {tr("Drainage"), "drainage_settings"},
        {tr("Electrical"), "electrical_settings"}, {tr("Structure"), "structure_settings"}};
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Engineering settings"));
    dialog.resize(720, 640);
    auto* layout = new QVBoxLayout(&dialog);
    auto* which = new QComboBox(&dialog);
    for (const Discipline& d : disciplines)
        which->addItem(d.label, QLatin1String(d.key));
    layout->addWidget(which);
    auto* table = new QTableWidget(&dialog);
    table->setObjectName(QStringLiteral("engineeringSettingsTable"));
    table->setColumnCount(3);
    table->setHorizontalHeaderLabels({tr("Setting"), tr("Value"), tr("Default")});
    table->horizontalHeader()->setStretchLastSection(true);
    layout->addWidget(table, 1);
    auto* hint = new QLabel(tr("Numbers, text, or a JSON table for new entries (for example a material). Defaults "
                               "follow EN 16798-1, EN 806-3/DIN 1988-300, EN 12056-2, IEC 60364 and the Eurocodes."),
        &dialog);
    hint->setWordWrap(true);
    layout->addWidget(hint);
    auto* buttons = new QHBoxLayout;
    layout->addLayout(buttons);
    auto* save = new QPushButton(tr("Save"), &dialog);
    auto* reset = new QPushButton(tr("Reset to defaults"), &dialog);
    auto* close = new QPushButton(tr("Close"), &dialog);
    buttons->addWidget(save);
    buttons->addWidget(reset);
    buttons->addStretch(1);
    buttons->addWidget(close);
    QList<QPair<QString, QJsonValue>> shown;
    auto load = [&] {
        const QString key = which->currentData().toString();
        const QJsonObject r = bridge("engineering_settings", {key});
        shown.clear();
        flatten(r.value("settings").toObject(), QString(), shown);
        QList<QPair<QString, QJsonValue>> defaults;
        flatten(r.value("defaults").toObject(), QString(), defaults);
        QHash<QString, QJsonValue> byPath;
        for (const auto& d : defaults)
            byPath.insert(d.first, d.second);
        table->setRowCount(shown.size());
        for (int i = 0; i < shown.size(); ++i) {
            auto* path = new QTableWidgetItem(shown[i].first);
            path->setFlags(path->flags() & ~Qt::ItemIsEditable);
            table->setItem(i, 0, path);
            const QJsonValue v = shown[i].second;
            table->setItem(i, 1, new QTableWidgetItem(v.isString() ? v.toString() : v.isDouble()
                ? QString::number(v.toDouble(), 'g', 10) : v.isObject() ? QStringLiteral("{}") : number(v, 0)));
            const QJsonValue d = byPath.value(shown[i].first);
            auto* def = new QTableWidgetItem(d.isUndefined() ? QString() : d.isString() ? d.toString()
                : QString::number(d.toDouble(), 'g', 10));
            def->setFlags(def->flags() & ~Qt::ItemIsEditable);
            table->setItem(i, 2, def);
        }
        table->resizeColumnToContents(0);
    };
    connect(which, &QComboBox::currentIndexChanged, &dialog, load);
    connect(save, &QPushButton::clicked, &dialog, [&] {
        QJsonObject changes;
        for (int i = 0; i < table->rowCount() && i < shown.size(); ++i) {
            const QString text = table->item(i, 1)->text().trimmed();
            const QJsonValue old = shown[i].second;
            QJsonValue now;
            if (old.isDouble()) {
                bool ok = false;
                const double d = QLocale().toDouble(text, &ok);
                now = ok ? QJsonValue(d) : QJsonValue(text.toDouble(&ok));
                if (!ok)
                    return showError(tr("Engineering settings"), tr("%1 must be a number").arg(shown[i].first));
            } else if (text.startsWith(QLatin1Char('{'))) {
                now = QJsonDocument::fromJson(text.toUtf8()).object();
            } else {
                now = text;
            }
            if (now != old)
                setPath(changes, shown[i].first.split(QLatin1Char('.')), now);
        }
        if (changes.isEmpty())
            return;
        const QJsonObject r = bridge("set_engineering_settings", {which->currentData().toString(), compact(changes)});
        if (!r.value("ok").toBool())
            return showError(tr("Engineering settings"), r.value("error").toString());
        setWindowModified(isDirty());
        load();
    });
    connect(reset, &QPushButton::clicked, &dialog, [&] {
        bridge("reset_engineering_settings", {which->currentData().toString()});
        setWindowModified(isDirty());
        load();
    });
    connect(close, &QPushButton::clicked, &dialog, &QDialog::accept);
    load();
    dialog.exec();
}

} // namespace kimbim
