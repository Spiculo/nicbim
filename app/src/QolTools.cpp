// SPDX-License-Identifier: GPL-3.0-or-later
// Everyday conveniences: the view's right-click menu, command search, Repeat last command, the Undo
// history panel and step labels, nudging with the arrow keys, object-snap and ortho toggles, dropped
// files and printing sheets.
#include "QolTools.h"

#include "DockLayout.h"
#include "DrawingView.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "MeasureOverlay.h"
#include "NodeGraph.h"
#include "SheetExport.h"
#include "SheetsPanel.h"
#include "Snapper.h"
#include "StatusStrip.h"
#include "Tracker.h"
#include "TwoPointTool.h"
#include "Underlay.h"
#include "Units.h"
#include "Viewport.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QJsonDocument>
#include <QJsonObject>

#include <algorithm>
#include <cmath>
#include <memory>
#include <optional>

#include <QAbstractButton>
#include <QAction>
#include <QActionGroup>
#include <QApplication>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QFileDialog>
#include <QFileInfo>
#include <QInputDialog>
#include <QJsonArray>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QMimeData>
#include <QMouseEvent>
#include <QPointer>
#include <QPrintDialog>
#include <QPrintPreviewDialog>
#include <QPrinter>
#include <QTimer>
#include <QTableWidget>
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>

namespace kimbim {

namespace {

// Folding for search: lower case, accents dropped ("Sección" finds "seccion").
QString folded(const QString& text)
{
    const QString decomposed = text.toLower().normalized(QString::NormalizationForm_D);
    QString out;
    out.reserve(decomposed.size());
    for (const QChar c : decomposed)
        if (c.category() != QChar::Mark_NonSpacing)
            out.append(c);
    return out;
}

void walk(QMenu* menu, const QString& path, QList<CommandEntry>* out)
{
    for (QAction* action : menu->actions()) {
        if (action->isSeparator() || !action->isVisible())
            continue;
        const QString text = commandText(action);
        if (QMenu* sub = action->menu()) {
            walk(sub, path.isEmpty() ? text : path + QStringLiteral(" > ") + text, out);
            continue;
        }
        if (text.isEmpty() || text.startsWith(QLatin1Char('(')))
            continue; // "(no saved workspaces)" and other placeholders
        out->append({path, text, action->shortcut().toString(QKeySequence::NativeText), action});
    }
}

} // namespace

QString commandText(const QAction* action)
{
    if (!action)
        return {};
    QString text = action->text();
    text.replace(QStringLiteral("&&"), QStringLiteral("\x01"));
    text.remove(QLatin1Char('&'));
    text.replace(QLatin1Char('\x01'), QLatin1Char('&'));
    return text.trimmed();
}

QList<CommandEntry> collectCommands(QWidget* window)
{
    QList<CommandEntry> out;
    if (!window)
        return out;
    QMenuBar* bar = window->findChild<QMenuBar*>();
    if (!bar)
        return out;
    QSet<QAction*> seen;
    QList<CommandEntry> all;
    for (QAction* top : bar->actions())
        if (QMenu* menu = top->menu())
            walk(menu, commandText(top), &all);
    for (const CommandEntry& e : all)
        if (!seen.contains(e.action)) { // one row per command, where it is first listed
            seen.insert(e.action);
            out.append(e);
        }
    return out;
}

QList<CommandEntry> filterCommands(const QList<CommandEntry>& commands, const QString& query)
{
    const QStringList words = folded(query).split(QLatin1Char(' '), Qt::SkipEmptyParts);
    if (words.isEmpty())
        return commands;
    QList<CommandEntry> starts, contains;
    for (const CommandEntry& e : commands) {
        const QString text = folded(e.text);
        const QString hay = text + QLatin1Char(' ') + folded(e.path);
        bool all = true;
        for (const QString& w : words)
            if (!hay.contains(w)) {
                all = false;
                break;
            }
        if (!all)
            continue;
        (text.startsWith(words.first()) ? starts : contains).append(e);
    }
    return starts + contains;
}

CommandSearchDialog::CommandSearchDialog(QWidget* window, QWidget* parent)
    : QDialog(parent)
    , m_commands(collectCommands(window))
{
    setObjectName(QStringLiteral("commandSearch"));
    setWindowTitle(tr("Search commands"));
    resize(520, 420);
    auto* layout = new QVBoxLayout(this);
    m_search = new QLineEdit(this);
    m_search->setObjectName(QStringLiteral("commandSearchText"));
    m_search->setPlaceholderText(tr("Type part of a command's name, then Enter"));
    m_search->setClearButtonEnabled(true);
    m_search->installEventFilter(this);
    layout->addWidget(m_search);
    m_list = new QListWidget(this);
    m_list->setObjectName(QStringLiteral("commandSearchList"));
    layout->addWidget(m_list);
    connect(m_search, &QLineEdit::textChanged, this, &CommandSearchDialog::refill);
    connect(m_list, &QListWidget::itemActivated, this, &CommandSearchDialog::choose);
    refill(QString());
}

void CommandSearchDialog::refill(const QString& query)
{
    m_list->clear();
    for (const CommandEntry& e : filterCommands(m_commands, query)) {
        QString label = e.text;
        if (!e.keys.isEmpty())
            label += QStringLiteral("    ") + e.keys;
        auto* item = new QListWidgetItem(label, m_list);
        item->setToolTip(e.path);
        if (!e.path.isEmpty())
            item->setText(label + QStringLiteral("    — ") + e.path);
        item->setData(Qt::UserRole, QVariant::fromValue(static_cast<QObject*>(e.action)));
        if (!e.action->isEnabled())
            item->setFlags(item->flags() & ~Qt::ItemIsEnabled);
    }
    for (int i = 0; i < m_list->count(); ++i)
        if (m_list->item(i)->flags() & Qt::ItemIsEnabled) {
            m_list->setCurrentRow(i);
            break;
        }
}

void CommandSearchDialog::choose(QListWidgetItem* item)
{
    if (!item || !(item->flags() & Qt::ItemIsEnabled))
        return;
    m_chosen = qobject_cast<QAction*>(item->data(Qt::UserRole).value<QObject*>());
    if (m_chosen)
        accept();
}

bool CommandSearchDialog::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == m_search && event->type() == QEvent::KeyPress) {
        auto* key = static_cast<QKeyEvent*>(event);
        if (key->key() == Qt::Key_Down || key->key() == Qt::Key_Up || key->key() == Qt::Key_PageDown
            || key->key() == Qt::Key_PageUp) {
            QApplication::sendEvent(m_list, event); // move through the results while typing
            return true;
        }
        if (key->key() == Qt::Key_Return || key->key() == Qt::Key_Enter) {
            choose(m_list->currentItem());
            return true;
        }
    }
    return QDialog::eventFilter(watched, event);
}

UndoHistoryPanel::UndoHistoryPanel(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("undoHistoryPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    auto* hint = new QLabel(tr("Click a step to go back to just after it."), this);
    hint->setWordWrap(true);
    layout->addWidget(hint);
    m_list = new QListWidget(this);
    m_list->setObjectName(QStringLiteral("undoHistoryList"));
    layout->addWidget(m_list);
    connect(m_list, &QListWidget::itemClicked, this, [this](QListWidgetItem* item) {
        const int row = m_list->row(item);
        if (row != m_current)
            emit jumpRequested(row - m_current);
    });
    setHistory({}, {});
}

void UndoHistoryPanel::setHistory(const QStringList& undo, const QStringList& redo)
{
    m_list->clear();
    new QListWidgetItem(tr("As opened"), m_list);
    for (const QString& label : undo)
        new QListWidgetItem(label, m_list);
    for (const QString& label : redo) {
        auto* item = new QListWidgetItem(label, m_list);
        item->setForeground(palette().brush(QPalette::Disabled, QPalette::Text));
        QFont f = item->font();
        f.setItalic(true);
        item->setFont(f);
    }
    m_current = int(undo.size());
    if (QListWidgetItem* now = m_list->item(m_current)) {
        QFont f = now->font();
        f.setBold(true);
        now->setFont(f);
        m_list->setCurrentItem(now);
        m_list->scrollToItem(now);
    }
}

CommandTracker::CommandTracker(std::function<void(QAction*)> started, QObject* parent)
    : QObject(parent)
    , m_started(std::move(started))
{
}

bool CommandTracker::eventFilter(QObject* watched, QEvent* event)
{
    switch (event->type()) {
    case QEvent::Shortcut:
        if (auto* action = qobject_cast<QAction*>(watched))
            m_started(action);
        break;
    case QEvent::MouseButtonRelease:
        if (auto* menu = qobject_cast<QMenu*>(watched)) {
            const auto* mouse = static_cast<QMouseEvent*>(event);
            if (QAction* action = menu->actionAt(mouse->position().toPoint()); action && !action->menu())
                m_started(action);
        } else if (auto* button = qobject_cast<QToolButton*>(watched)) {
            if (button->defaultAction() && button->rect().contains(static_cast<QMouseEvent*>(event)->position().toPoint()))
                m_started(button->defaultAction());
        }
        break;
    case QEvent::KeyPress:
        if (auto* menu = qobject_cast<QMenu*>(watched)) {
            const int key = static_cast<QKeyEvent*>(event)->key();
            if ((key == Qt::Key_Return || key == Qt::Key_Enter) && menu->activeAction() && !menu->activeAction()->menu())
                m_started(menu->activeAction());
        }
        break;
    default:
        break;
    }
    return false;
}

QString faceFromNormal(double nx, double ny, double nz)
{
    const double ax = std::abs(nx), ay = std::abs(ny), az = std::abs(nz);
    if (az >= ax && az >= ay)
        return nz >= 0 ? QStringLiteral("+z") : QStringLiteral("-z");
    if (ax >= ay)
        return nx >= 0 ? QStringLiteral("+x") : QStringLiteral("-x");
    return ny >= 0 ? QStringLiteral("+y") : QStringLiteral("-y");
}

QString dropKind(const QString& path)
{
    const QFileInfo info(path);
    if (info.isDir())
        return QStringLiteral("open");
    const QString suffix = info.suffix().toLower();
    if (suffix == QLatin1String("nic") || suffix == QLatin1String("ifc"))
        return QStringLiteral("open");
    static const QStringList underlays{"dxf", "dwg", "pdf", "png", "jpg", "jpeg"};
    static const QStringList meshes{"obj", "stl", "ply", "dae", "gltf", "glb", "fbx"};
    static const QStringList clouds{"xyz", "pts", "las", "laz", "e57"};
    if (underlays.contains(suffix))
        return QStringLiteral("underlay");
    if (meshes.contains(suffix))
        return QStringLiteral("mesh");
    if (clouds.contains(suffix))
        return QStringLiteral("cloud");
    return {};
}

// ---------------------------------------------------------------- MainWindow

namespace {

// Commands Repeat last command never repeats: navigation, files, undo itself and the like.
bool repeatable(const QAction* action)
{
    static const QStringList never{"actionUndo", "actionRedo", "actionRepeatLast", "actionSearchCommands",
        "actionSave", "actionSaveAs", "actionSaveAsFolder", "actionOpen", "actionOpenProject", "actionNewProject",
        "actionQuit", "actionPreferences", "actionKeyboardShortcuts", "actionSelectTool", "actionFitAll",
        "actionZoomToSelection", "actionObjectSnaps", "actionOrthoLock", "actionShowProperties",
        "actionPrintSheet"};
    const QString name = action ? action->objectName() : QString();
    return name.startsWith(QLatin1String("action")) && !never.contains(name) && !action->isSeparator()
        && !action->menu();
}

} // namespace

void MainWindow::buildQolTools()
{
    // What the user starts: its text names the undo step it makes; repeatable ones are remembered.
    auto* tracker = new CommandTracker([this](QAction* a) { noteCommand(a); }, this);
    qApp->installEventFilter(tracker);

    m_repeatLast = new QAction(tr("&Repeat last command"), this);
    m_repeatLast->setObjectName(QStringLiteral("actionRepeatLast"));
    m_repeatLast->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_R));
    m_repeatLast->setEnabled(false);
    connect(m_repeatLast, &QAction::triggered, this, [this] {
        if (m_lastCommand)
            runCommand(m_lastCommand);
    });
    QAction* search = new QAction(tr("&Search commands..."), this);
    search->setObjectName(QStringLiteral("actionSearchCommands"));
    search->setShortcuts({QKeySequence(Qt::CTRL | Qt::Key_K), QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_P)});
    search->setToolTip(tr("Find any command by typing part of its name"));
    connect(search, &QAction::triggered, this, &MainWindow::showCommandSearch);
    QAction* props = new QAction(tr("&Properties"), this);
    props->setObjectName(QStringLiteral("actionShowProperties"));
    props->setShortcut(QKeySequence(Qt::CTRL | Qt::Key_T));
    props->setToolTip(tr("Show the selection's properties"));
    connect(props, &QAction::triggered, this, [this] {
        if (!m_selection.isEmpty())
            m_dock->raisePanel(QStringLiteral("properties"));
    });
    if (auto* edit = m_undo ? qobject_cast<QMenu*>(m_undo->parent()) : nullptr) { // just after Redo
        const QList<QAction*> actions = edit->actions();
        const int at = int(actions.indexOf(m_redo));
        edit->insertAction(at >= 0 && at + 1 < actions.size() ? actions.at(at + 1) : nullptr, m_repeatLast);
        edit->addSeparator();
        edit->addAction(props);
    } else {
        addAction(m_repeatLast);
        addAction(props);
    }
    if (m_helpMenu)
        m_helpMenu->insertAction(m_helpMenu->actions().value(0), search);
    else
        addAction(search);

    // Object snaps (F3) and the ortho lock (F8), also as buttons in the status bar.
    m_objectSnaps = new QAction(tr("Object &snaps"), this);
    m_objectSnaps->setObjectName(QStringLiteral("actionObjectSnaps"));
    m_objectSnaps->setCheckable(true);
    m_objectSnaps->setChecked(Snapper::objectSnapsEnabled());
    m_objectSnaps->setShortcut(QKeySequence(Qt::Key_F3));
    m_objectSnaps->setToolTip(tr("Snap to ends, middles, crossings and other points of elements (F3)"));
    connect(m_objectSnaps, &QAction::toggled, this, [this](bool on) {
        Snapper::setObjectSnapsEnabled(on);
        m_status->showMessage(on ? tr("Object snaps on") : tr("Object snaps off"), 2000);
    });
    m_orthoAction = new QAction(tr("&Ortho"), this);
    m_orthoAction->setObjectName(QStringLiteral("actionOrthoLock"));
    m_orthoAction->setCheckable(true);
    m_orthoAction->setShortcut(QKeySequence(Qt::Key_F8));
    m_orthoAction->setToolTip(tr("Keep drawing at right angles without holding Shift (F8); Shift then frees it"));
    connect(m_orthoAction, &QAction::toggled, this, [this](bool on) {
        m_orthoLock = on;
        m_status->showMessage(on ? tr("Ortho on") : tr("Ortho off"), 2000);
    });
    // The user origin: typed absolute x, y are measured from it (a project setting).
    auto* setOrigin = new QAction(tr("Set user &origin"), this);
    setOrigin->setObjectName(QStringLiteral("actionSetUserOrigin"));
    setOrigin->setToolTip(tr("Click the point that typed absolute x, y are measured from"));
    connect(setOrigin, &QAction::triggered, this, [this] {
        pickPoints(1, false, {tr("User origin: click the point typed x, y are measured from (Esc cancels)")},
            [this](const QVector<QPointF>& p, const QString&) { setUserOrigin(p.at(0)); });
    });
    auto* resetOrigin = new QAction(tr("Reset user origin"), this);
    resetOrigin->setObjectName(QStringLiteral("actionResetUserOrigin"));
    connect(resetOrigin, &QAction::triggered, this, [this] { setUserOrigin(QPointF()); });
    if (m_viewMenu) {
        m_viewMenu->addSeparator();
        m_viewMenu->addAction(m_objectSnaps);
        m_viewMenu->addAction(m_orthoAction);
        m_viewMenu->addAction(setOrigin);
        m_viewMenu->addAction(resetOrigin);
    } else {
        addAction(setOrigin);
        addAction(resetOrigin);
    }
    m_status->addToggle(m_objectSnaps);
    m_status->addToggle(m_orthoAction);

    QAction* print = new QAction(tr("&Print sheet..."), this);
    print->setObjectName(QStringLiteral("actionPrintSheet"));
    print->setShortcut(QKeySequence::Print);
    print->setToolTip(tr("Print the open or selected sheet, with a preview"));
    connect(print, &QAction::triggered, this, &MainWindow::printSheetDialog);
    // Clip a DXF/DWG/vector-PDF underlay to a clicked rectangle (D232), next to File > Underlays.
    auto* clip = new QAction(tr("C&lip underlay..."), this);
    clip->setObjectName(QStringLiteral("actionClipUnderlay"));
    clip->setToolTip(tr("Show and snap to only the part of an underlay inside a clicked rectangle"));
    connect(clip, &QAction::triggered, this, [this] { clipUnderlayCommand(false); });
    auto* unclip = new QAction(tr("Clear underlay clip..."), this);
    unclip->setObjectName(QStringLiteral("actionClearUnderlayClip"));
    connect(unclip, &QAction::triggered, this, [this] { clipUnderlayCommand(true); });
    QAction* underlays = findChild<QAction*>(QStringLiteral("actionUnderlays"));
    if (auto* fileMenu = underlays ? qobject_cast<QMenu*>(underlays->parent()) : nullptr) {
        const QList<QAction*> acts = fileMenu->actions();
        const int at = int(acts.indexOf(underlays));
        QAction* before = at >= 0 && at + 1 < acts.size() ? acts.at(at + 1) : nullptr;
        fileMenu->insertAction(before, clip);
        fileMenu->insertAction(before, unclip);
    } else {
        addAction(clip);
        addAction(unclip);
    }
    QAction* pdf = findChild<QAction*>(QStringLiteral("actionExportSheetPdf"));
    if (auto* file = pdf ? qobject_cast<QMenu*>(pdf->parent()) : nullptr)
        file->insertAction(pdf, print);
    else
        addAction(print);

    onEachView([this](Viewport* v) {
        connect(v, &Viewport::contextMenuRequested, this, [this, v](const QPoint& at, const QString& guid) {
            if (!guid.isEmpty() && !m_selection.contains(guid)) { // right-click picks what is under it
                v->selectGuids({guid});
                setSelection({guid});
            }
            QMenu* menu = buildViewContextMenu();
            menu->setAttribute(Qt::WA_DeleteOnClose);
            menu->popup(at);
        });
        connect(v, &Viewport::nudgeRequested, this, [this](int dx, int dy, bool coarse) { nudgeSelection(dx, dy, coarse); });
    });
    connectPickSignals();
    setAcceptDrops(true);
    buildFinishAndMepCommands();
    buildPhaseMenu();
    groupModelMenu();
    buildEngineeringMenu(); // D248: MEP and structure move out of Model into Engineering
}

void MainWindow::setUserOrigin(QPointF origin)
{
    Tracker::setUserOrigin(origin);
    setProjectSettings({{"user_origin", QJsonArray{origin.x(), origin.y()}}});
    m_status->showMessage(origin.isNull() ? tr("User origin reset to the project origin")
                                          : tr("User origin at %1, %2").arg(formatLength(origin.x()), formatLength(origin.y())), 3000);
}

void MainWindow::buildFinishAndMepCommands()
{
    QMenu* model = nullptr;
    for (QAction* top : m_menuBar->actions())
        if (top->menu() && top->menu()->title() == tr("&Model"))
            model = top->menu();
    auto add = [&](const QString& text, const char* name, const QString& tip, auto&& run) {
        auto* a = model ? model->addAction(text) : new QAction(text, this);
        if (!model)
            addAction(a);
        a->setObjectName(QLatin1String(name));
        a->setToolTip(tip);
        connect(a, &QAction::triggered, this, run);
        return a;
    };
    add(tr("&Floor finish..."), "actionFloorFinish", tr("A floor finish over each selected room"),
        [this] { finishCommand(QStringLiteral("floor")); });
    add(tr("S&kirting..."), "actionSkirting", tr("A skirting just inside the walls of each selected room"),
        [this] { finishCommand(QStringLiteral("skirting")); });
    add(tr("Wall &finish..."), "actionWallFinish", tr("Plaster or tiles on the walls of each selected room"),
        [this] { finishCommand(QStringLiteral("wall")); });
    add(tr("S&haft..."), "actionShaft", tr("Cut a rectangle through every slab from this level up to another"),
        [this] { shaftCommand(); });
    add(tr("&Duct..."), "actionDuct", tr("Draw a straight duct run: click its points, Esc ends"),
        [this] { mepCommand(QStringLiteral("duct")); });
    add(tr("&Pipe..."), "actionPipe", tr("Draw a straight pipe run: click its points, Esc ends"),
        [this] { mepCommand(QStringLiteral("pipe")); });
    add(tr("Cable &tray..."), "actionCableTray", tr("Draw a straight cable-tray run: click its points, Esc ends"),
        [this] { mepCommand(QStringLiteral("cable_tray")); });
    add(tr("&Kerb..."), "actionKerb", tr("A kerb along a path: click its points, Enter finishes"), [this] {
        pickPoints(-2, false, {tr("Kerb: click where it starts"), tr("Kerb: click the next point; Enter finishes, Esc cancels")},
            [this](const QVector<QPointF>& p, const QString&) {
                QJsonArray points;
                for (const QPointF& q : p)
                    points.append(QJsonArray{q.x(), q.y()});
                const QJsonObject r = bridge("create_kerb", {m_levels->activeStorey(),
                    QString::fromUtf8(QJsonDocument(points).toJson(QJsonDocument::Compact)), QStringLiteral("0.15"),
                    QStringLiteral("0.15")});
                if (!r.value("ok").toBool()) {
                    showError(tr("Kerb"), r.value("error").toString());
                    return;
                }
                m_pendingLabel = tr("Kerb");
                afterEdit(r);
                m_pendingLabel.clear();
            });
    });
    add(tr("&Road marking..."), "actionRoadMarking", tr("Painted lines along a path: solid, dashed or double"), [this] {
        QString style = QStringLiteral("dashed");
        if (!m_quiet) {
            const QStringList styles{tr("Dashed"), tr("Solid"), tr("Double")};
            bool ok = false;
            const QString chosen = QInputDialog::getItem(this, tr("Road marking"), tr("Style:"), styles, 0, false, &ok);
            if (!ok)
                return;
            style = QStringList{QStringLiteral("dashed"), QStringLiteral("solid"), QStringLiteral("double")}.at(int(styles.indexOf(chosen)));
        }
        pickPoints(-2, false, {tr("Road marking: click where it starts"), tr("Road marking: click the next point; Enter finishes")},
            [this, style](const QVector<QPointF>& p, const QString&) {
                QJsonArray points;
                for (const QPointF& q : p)
                    points.append(QJsonArray{q.x(), q.y()});
                const QJsonObject r = bridge("create_road_marking", {m_levels->activeStorey(),
                    QString::fromUtf8(QJsonDocument(points).toJson(QJsonDocument::Compact)), style});
                if (!r.value("ok").toBool()) {
                    showError(tr("Road marking"), r.value("error").toString());
                    return;
                }
                m_pendingLabel = tr("Road marking");
                afterEdit(r);
                m_pendingLabel.clear();
            });
    });
    add(tr("&Planting area..."), "actionPlantingArea", tr("A planting bed: click its outline, Enter closes it"), [this] {
        QString planting;
        if (!m_quiet) {
            bool ok = false;
            planting = QInputDialog::getText(this, tr("Planting area"), tr("Planting (species or mix):"), QLineEdit::Normal,
                QString(), &ok);
            if (!ok)
                return;
        }
        pickPoints(-3, false, {tr("Planting area: click the first corner"), tr("Planting area: click the next corner; Enter closes it")},
            [this, planting](const QVector<QPointF>& p, const QString&) {
                QJsonArray points;
                for (const QPointF& q : p)
                    points.append(QJsonArray{q.x(), q.y()});
                const QJsonObject r = bridge("create_planting_area", {m_levels->activeStorey(),
                    QString::fromUtf8(QJsonDocument(points).toJson(QJsonDocument::Compact)), QStringLiteral("0.3"), planting});
                if (!r.value("ok").toBool()) {
                    showError(tr("Planting area"), r.value("error").toString());
                    return;
                }
                m_pendingLabel = tr("Planting area");
                afterEdit(r);
                m_pendingLabel.clear();
            });
    });
    add(tr("Terrain from &clicked points..."), "actionTerrainPoints",
        tr("Click survey points in the view, then type each one's height"), [this] {
            pickPoints(-3, false, {tr("Terrain: click the first survey point"),
                                      tr("Terrain: click the next survey point; Enter when done (at least 3)")},
                [this](const QVector<QPointF>& p, const QString&) { terrainHeightsDialog(p); });
        });
    add(tr("&Handrail on wall..."), "actionWallHandrail", tr("A handrail fixed to a face of each selected wall"), [this] {
        if (m_selection.isEmpty()) {
            m_status->showMessage(tr("Select one or more walls first"));
            return;
        }
        QString side = QStringLiteral("left");
        if (!m_quiet) {
            bool ok = false;
            const QStringList sides{tr("Left of the wall's direction"), tr("Right of the wall's direction")};
            const QString chosen = QInputDialog::getItem(this, tr("Handrail on wall"), tr("Face:"), sides, 0, false, &ok);
            if (!ok)
                return;
            side = sides.indexOf(chosen) == 1 ? QStringLiteral("right") : QStringLiteral("left");
        }
        int made = 0;
        for (const QString& wall : m_selection) {
            const QJsonObject r = bridge("wall_handrail", {wall, side, QStringLiteral("0.9")});
            if (r.value("ok").toBool()) {
                afterEdit(r);
                ++made;
            } else if (m_selection.size() == 1) {
                showError(tr("Handrail on wall"), r.value("error").toString());
            }
        }
        if (made)
            m_status->showMessage(tr("%n handrail(s) added", nullptr, made));
    });
    auto detailOnly = [this](bool only) {
        if (m_selection.isEmpty()) {
            m_status->showMessage(tr("Select 2D elements first"));
            return;
        }
        QString detail;
        if (only) {
            QStringList names, guids;
            for (const auto& v : bridge("drawings").value("drawings").toArray())
                if (v.toObject().value("kind").toString() == QLatin1String("detail")) {
                    names << v.toObject().value("name").toString();
                    guids << v.toObject().value("guid").toString();
                }
            if (guids.isEmpty()) {
                m_status->showMessage(tr("There is no detail drawing yet: draw one with the Detail tool"));
                return;
            }
            int index = 0;
            if (!m_quiet && guids.size() > 1) {
                bool ok = false;
                const QString name = QInputDialog::getItem(this, tr("Show only on a detail"), tr("Detail:"), names, 0, false, &ok);
                if (!ok)
                    return;
                index = int(names.indexOf(name));
            }
            detail = guids.at(index);
        }
        const QJsonObject r = bridge("set_detail_only",
            {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact)), detail});
        if (!r.value("ok").toBool()) {
            showError(tr("Detail 2D"), r.value("error").toString());
            return;
        }
        afterEdit(r);
        m_status->showMessage(only ? tr("Shown only on the detail drawing") : tr("Shown on every drawing of the level"), 3000);
    };
    add(tr("Show only on a &detail..."), "actionDetailOnly",
        tr("The selected 2D appears on one detail drawing and not on the level's plan"), [detailOnly] { detailOnly(true); });
    add(tr("Show on every drawing"), "actionDetailOnlyClear", tr("The selected 2D appears on every drawing of its level again"),
        [detailOnly] { detailOnly(false); });
    add(tr("Visual script &graph..."), "actionVisualGraph",
        tr("Build a visual script by wiring nodes: each node's result feeds the inputs it is wired to"),
        [this] { visualGraphDialog(); });
    add(tr("&Edit model in place"), "actionEditInPlace",
        tr("Edit the selected placed model where it is: the changes go to the model and every placement"),
        [this] { editInstanceInPlace(true); });
    add(tr("&Finish editing in place"), "actionFinishInPlace", tr("Stop sending edits back to the model"),
        [this] { editInstanceInPlace(false); });
    add(tr("Save model to &library..."), "actionSaveModelToLibrary", tr("Save a model in the office library for other projects"),
        [this] { saveModelToLibrary(); });
    add(tr("Load model from l&ibrary..."), "actionLoadModelFromLibrary", tr("Bring a model saved in the library into this project"),
        [this] { loadModelFromLibrary(); });
    add(tr("&Area label..."), "actionAreaLabel", tr("Click an outline: its area goes in a label at its middle"), [this] {
        pickPoints(-3, false, {tr("Area label: click the first corner"), tr("Area label: click the next corner; Enter places the label")},
            [this](const QVector<QPointF>& p, const QString&) {
                double twice = 0.0, cx = 0.0, cy = 0.0;
                for (int i = 0; i < p.size(); ++i) {
                    const QPointF a = p.at(i), b = p.at((i + 1) % p.size());
                    const double cross = a.x() * b.y() - b.x() * a.y();
                    twice += cross;
                    cx += (a.x() + b.x()) * cross;
                    cy += (a.y() + b.y()) * cross;
                }
                if (std::abs(twice) < 1e-9) {
                    m_status->showMessage(tr("Area label: the outline has no area"));
                    return;
                }
                const QPointF centre(cx / (3 * twice), cy / (3 * twice));
                m_pendingLabel = tr("Area label");
                addAnnotation(QStringLiteral("text"), {centre}, formatArea(std::abs(twice) / 2));
                m_pendingLabel.clear();
            });
    });
    auto openingFinish = [this](const char* fn, const QString& title) {
        const QJsonObject r = bridge(fn, {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact))});
        if (!r.value("ok").toBool()) {
            showError(title, r.value("error").toString());
            return;
        }
        afterEdit(r);
        m_status->showMessage(tr("%1: %n element(s) added", nullptr, int(r.value("guids").toArray().size())).arg(title));
    };
    add(tr("&Sills"), "actionSills", tr("A sill under each selected window, door or wall opening"),
        [openingFinish, this] { openingFinish("add_sills", tr("Sills")); });
    add(tr("&Reveals"), "actionReveals", tr("Reveal linings on the jambs and head of each selected opening"),
        [openingFinish, this] { openingFinish("add_reveals", tr("Reveals")); });
    add(tr("&Beam system..."), "actionBeamSystem", tr("Joists or rafters at a spacing across an area: click two corners"),
        [this] { beamSystemCommand(); });
    add(tr("&Lintels"), "actionLintels", tr("A lintel over each selected door, window or wall opening"), [this] {
        const QJsonObject r = bridge("add_lintels",
            {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact)),
                QStringLiteral("0.15"), QStringLiteral("0.2")});
        if (!r.value("ok").toBool()) {
            showError(tr("Lintels"), r.value("error").toString());
            return;
        }
        afterEdit(r);
        m_status->showMessage(tr("%n lintel(s) added", nullptr, int(r.value("guids").toArray().size())));
    });
    add(tr("&Interior elevations"), "actionInteriorElevations",
        tr("An elevation of each wall of the selected room, seen from inside it"), [this] {
            if (m_selection.size() != 1) {
                m_status->showMessage(tr("Select one room first"));
                return;
            }
            const QJsonObject r = bridge("interior_elevations", {m_selection.first(), QStringLiteral("0.5")});
            if (!r.value("ok").toBool()) {
                showError(tr("Interior elevations"), r.value("error").toString());
                return;
            }
            afterEdit(r);
            m_status->showMessage(tr("%n interior elevation(s) added to the Drawings panel", nullptr,
                int(r.value("guids").toArray().size())));
        });
}

void MainWindow::clipUnderlayCommand(bool clear)
{
    QVector<Underlay> lineworks;
    QStringList names;
    for (const auto& v : bridge("underlays").value("underlays").toArray()) {
        const Underlay u = Underlay::fromJson(v.toObject());
        if (!u.isRaster() && (!clear || !u.clip.isNull())) {
            lineworks << u;
            names << u.name;
        }
    }
    if (lineworks.isEmpty()) {
        m_status->showMessage(clear ? tr("No underlay is clipped") : tr("No DXF, DWG or vector-PDF underlay to clip"));
        return;
    }
    int index = 0;
    if (!m_quiet && lineworks.size() > 1) {
        bool ok = false;
        const QString name = QInputDialog::getItem(this, clear ? tr("Clear underlay clip") : tr("Clip underlay"),
            tr("Underlay:"), names, 0, false, &ok);
        if (!ok)
            return;
        index = int(names.indexOf(name));
    }
    const Underlay u = lineworks.at(index);
    auto apply = [this, u](const QJsonArray& clip) {
        const QJsonObject r = bridge("set_underlay", {u.id,
            QString::fromUtf8(QJsonDocument(QJsonObject{{"clip", clip}}).toJson(QJsonDocument::Compact))});
        if (!r.value("ok").toBool()) {
            showError(tr("Clip underlay"), r.value("error").toString());
            return;
        }
        refreshUnderlays();
        m_status->showMessage(clip.isEmpty() ? tr("Underlay %1 shown whole again").arg(u.name)
                                             : tr("Underlay %1 clipped").arg(u.name), 3000);
    };
    if (clear) {
        apply(QJsonArray());
        return;
    }
    pickPoints(2, true, {tr("Clip underlay: click a corner of what to keep"), tr("Clip underlay: click the opposite corner (Esc cancels)")},
        [u, apply](const QVector<QPointF>& p, const QString&) {
            // the clicked rectangle in the drawing's own units (it may be turned on the level)
            QRectF box;
            for (const QPointF& c : {p.at(0), QPointF(p.at(1).x(), p.at(0).y()), p.at(1), QPointF(p.at(0).x(), p.at(1).y())}) {
                const QPointF d = u.placement.toDrawing(c);
                box = box.isNull() ? QRectF(d, QSizeF(0, 0)) : box.united(QRectF(d, QSizeF(0, 0)));
            }
            if (box.width() <= 0 || box.height() <= 0)
                return;
            apply(QJsonArray{box.left(), box.top(), box.right(), box.bottom()});
        });
}

// ---------------------------------------------------------------- D234: Revit-style phases

QSet<QString> MainWindow::phaseHidden()
{
    QSet<QString> out;
    m_phaseDemolished.clear();
    const QJsonObject r = bridge("phase_filter");
    if (!r.value("ok").toBool())
        return out;
    for (const auto& v : r.value("hidden").toArray())
        out.insert(v.toString());
    for (const auto& v : r.value("demolished").toArray())
        m_phaseDemolished << v.toString();
    // demolished elements in the phase show in red, as Revit's phase graphic overrides do
    if (m_viewport) {
        QHash<QString, QColor> colours;
        for (const QString& g : std::as_const(m_phaseDemolished))
            colours.insert(g, QColor(200, 40, 40));
        if (!colours.isEmpty() || m_phaseColoured)
            m_viewport->setElementColors(colours);
        m_phaseColoured = !colours.isEmpty();
    }
    return out;
}

void MainWindow::buildPhaseMenu()
{
    if (!m_viewMenu)
        return;
    QMenu* menu = m_viewMenu->addMenu(tr("P&hases"));
    menu->setObjectName(QStringLiteral("phasesMenu"));
    connect(menu, &QMenu::aboutToShow, this, [this, menu] {
        menu->clear();
        const QJsonObject p = bridge("building_phases");
        const QString current = p.value("phase").toString(), filter = p.value("filter").toString();
        auto* phaseGroup = new QActionGroup(menu);
        for (const auto& v : p.value("phases").toArray()) {
            const QString name = v.toString();
            QAction* a = menu->addAction(name);
            a->setCheckable(true);
            a->setChecked(name == current);
            phaseGroup->addAction(a);
            connect(a, &QAction::triggered, this, [this, name, filter] { setPhaseView(name, filter); });
        }
        menu->addSeparator();
        const QList<QPair<QString, QString>> filters{{QStringLiteral("all"), tr("Show all")},
            {QStringLiteral("complete"), tr("Show complete")}, {QStringLiteral("new"), tr("Show new")},
            {QStringLiteral("existing"), tr("Show previous and demolished")}};
        auto* filterGroup = new QActionGroup(menu);
        for (const auto& [key, label] : filters) {
            QAction* a = menu->addAction(label);
            a->setCheckable(true);
            a->setChecked(key == filter);
            filterGroup->addAction(a);
            connect(a, &QAction::triggered, this, [this, current, key = key] { setPhaseView(current, key); });
        }
        menu->addSeparator();
        QAction* assign = menu->addAction(tr("Assign selection to a phase..."));
        assign->setObjectName(QStringLiteral("actionAssignPhase"));
        connect(assign, &QAction::triggered, this, &MainWindow::assignPhaseDialog);
        QAction* edit = menu->addAction(tr("Edit phases..."));
        edit->setObjectName(QStringLiteral("actionEditPhases"));
        connect(edit, &QAction::triggered, this, [this] {
            const QJsonObject p = bridge("building_phases");
            QStringList names;
            for (const auto& v : p.value("phases").toArray())
                names << v.toString();
            bool ok = false;
            const QString text = QInputDialog::getMultiLineText(this, tr("Edit phases"),
                tr("One phase per line, oldest first:"), names.join(QLatin1Char('\n')), &ok);
            if (!ok)
                return;
            QStringList edited;
            for (const QString& line : text.split(QLatin1Char('\n')))
                if (!line.trimmed().isEmpty())
                    edited << line.trimmed();
            const QJsonObject r = bridge("set_phases",
                {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(edited)).toJson(QJsonDocument::Compact))});
            if (!r.value("ok").toBool())
                showError(tr("Edit phases"), r.value("error").toString());
            reloadProjectSettings();
            refreshLayers();
        });
    });
}

bool MainWindow::setPhaseView(const QString& phase, const QString& filter)
{
    const QJsonObject r = bridge("set_phase_view", {phase, filter});
    if (!r.value("ok").toBool()) {
        showError(tr("Phases"), r.value("error").toString());
        return false;
    }
    reloadProjectSettings();
    refreshLayers();
    m_status->showMessage(tr("Showing phase %1").arg(phase), 3000);
    return true;
}

void MainWindow::assignPhaseDialog()
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select elements first"));
        return;
    }
    const QJsonObject p = bridge("building_phases");
    QStringList names;
    for (const auto& v : p.value("phases").toArray())
        names << v.toString();
    QString created = p.value("phase").toString(), demolished;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Assign phase"));
        auto* form = new QFormLayout(&dialog);
        auto* made = new QComboBox(&dialog);
        made->addItems(names);
        made->setCurrentText(created);
        auto* gone = new QComboBox(&dialog);
        gone->addItem(tr("None"), QString());
        for (const QString& n : names)
            gone->addItem(n, n);
        form->addRow(tr("Created in:"), made);
        form->addRow(tr("Demolished in:"), gone);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        created = made->currentText();
        demolished = gone->currentData().toString();
    }
    const QJsonObject r = bridge("assign_building_phase",
        {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact)), created,
            demolished});
    if (!r.value("ok").toBool()) {
        showError(tr("Assign phase"), r.value("error").toString());
        return;
    }
    afterEdit(r);
    refreshLayers();
}

// ---------------------------------------------------------------- D237: models in place and in the library

bool MainWindow::editInstanceInPlace(bool on)
{
    if (!on) {
        bridge("end_edit_in_place");
        m_status->showMessage(tr("Finished editing the model in place"), 3000);
        return true;
    }
    QString instance;
    for (const QString& g : std::as_const(m_selection))
        if (m_instanceOf.contains(g)) {
            instance = m_instanceOf.value(g);
            break;
        }
    if (instance.isEmpty()) {
        m_status->showMessage(tr("Select an element of a placed model first"));
        return false;
    }
    const QJsonObject r = bridge("begin_edit_in_place", {instance});
    if (!r.value("ok").toBool()) {
        showError(tr("Edit in place"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Editing model %1 in place: its changes go to every placement. "
                             "Model > Finish editing in place when done").arg(r.value("name").toString()));
    return true;
}

QString MainWindow::chooseModel(const QString& title)
{
    QStringList names, guids;
    for (const auto& v : bridge("models").value("models").toArray()) {
        names << v.toObject().value("name").toString();
        guids << v.toObject().value("guid").toString();
    }
    if (guids.isEmpty()) {
        m_status->showMessage(tr("There are no models yet: use New model... next to the levels"));
        return {};
    }
    if (m_quiet || guids.size() == 1)
        return guids.first();
    bool ok = false;
    const QString name = QInputDialog::getItem(this, title, tr("Model:"), names, 0, false, &ok);
    return ok ? guids.at(int(names.indexOf(name))) : QString();
}

bool MainWindow::saveModelToLibrary(const QString& folder)
{
    const QString model = chooseModel(tr("Save model to library"));
    if (model.isEmpty())
        return false;
    QString target = folder.isEmpty() ? m_prefs.value(QStringLiteral("office_library")).toString() : folder;
    if (target.isEmpty() && !m_quiet)
        target = QFileDialog::getExistingDirectory(this, tr("Library folder"));
    if (target.isEmpty())
        return false;
    const QJsonObject r = bridge("save_model_to_library", {model, target});
    if (!r.value("ok").toBool()) {
        showError(tr("Save model to library"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Model saved to %1").arg(r.value("path").toString()), 4000);
    return true;
}

bool MainWindow::loadModelFromLibrary(const QString& path)
{
    QString file = path;
    if (file.isEmpty()) {
        const QString folder = m_prefs.value(QStringLiteral("office_library")).toString();
        QStringList names, paths;
        for (const auto& v : bridge("library_models", {folder}).value("models").toArray()) {
            names << v.toObject().value("name").toString();
            paths << v.toObject().value("path").toString();
        }
        if (!names.isEmpty() && !m_quiet) {
            names << tr("Another file...");
            bool ok = false;
            const QString name = QInputDialog::getItem(this, tr("Load model from library"), tr("Model:"), names, 0, false, &ok);
            if (!ok)
                return false;
            const int i = int(names.indexOf(name));
            file = i < paths.size() ? paths.at(i) : QString();
        } else if (!paths.isEmpty()) {
            file = paths.first();
        }
        if (file.isEmpty() && !m_quiet)
            file = QFileDialog::getOpenFileName(this, tr("Load model from library"), folder, tr("Library models (*.nicmodel.ifc)"));
    }
    if (file.isEmpty())
        return false;
    const QJsonObject r = bridge("load_model_from_library", {file, QString()});
    if (!r.value("ok").toBool()) {
        showError(tr("Load model from library"), r.value("error").toString());
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("Model %1 loaded: place it with the Place model tool").arg(r.value("name").toString()), 4000);
    return true;
}

// ---------------------------------------------------------------- D238: visual scripts as a node graph

NodeGraphDialog* MainWindow::makeGraphDialog(const QString& script)
{
    QJsonObject graph;
    if (!script.isEmpty())
        for (const auto& v : bridge("pipelines").value("pipelines").toArray())
            if (v.toObject().value("name").toString() == script)
                graph = bridge("steps_to_graph",
                    {QString::fromUtf8(QJsonDocument(v.toObject().value("steps").toArray()).toJson(QJsonDocument::Compact))});
    auto* dialog = new NodeGraphDialog(bridge("pipeline_ops").value("ops").toArray(),
        script.isEmpty() ? tr("New script") : script, graph, this);
    dialog->onSave = [this](const QString& name, const QJsonObject& g) -> QString {
        const QJsonObject r = bridge("save_graph", {name, QString::fromUtf8(QJsonDocument(g).toJson(QJsonDocument::Compact))});
        if (!r.value("ok").toBool())
            return r.value("error").toString();
        reloadProjectSettings();
        return {};
    };
    dialog->onRun = [this](const QString& name) -> QString {
        const QJsonObject r = bridge("run_pipeline", {name, m_levels->activeStorey()});
        if (!r.value("ok").toBool())
            return r.value("error").toString();
        m_pendingLabel = name;
        afterEdit(r);
        m_pendingLabel.clear();
        m_status->showMessage(tr("Ran \"%1\": %n step(s)", nullptr, r.value("changed").toInt()).arg(name), 3000);
        return {};
    };
    return dialog;
}

void MainWindow::visualGraphDialog()
{
    QStringList names;
    for (const auto& v : bridge("pipelines").value("pipelines").toArray())
        names << v.toObject().value("name").toString();
    QString script;
    if (!names.isEmpty()) {
        const QString fresh = tr("(new script)");
        bool ok = false;
        const QString chosen = QInputDialog::getItem(this, tr("Visual script graph"), tr("Script:"), QStringList{fresh} + names,
            0, false, &ok);
        if (!ok)
            return;
        if (chosen != fresh)
            script = chosen;
    }
    std::unique_ptr<NodeGraphDialog> dialog(makeGraphDialog(script));
    dialog->exec();
}

void MainWindow::terrainHeightsDialog(const QVector<QPointF>& points)
{
    // Each clicked point with its height (absolute metres); quiet mode keeps the level's height.
    const double level = m_levels->activeElevation();
    QVector<double> heights(points.size(), level);
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Terrain heights"));
        auto* layout = new QVBoxLayout(&dialog);
        layout->addWidget(new QLabel(tr("The height of each survey point above the project zero:"), &dialog));
        auto* table = new QTableWidget(int(points.size()), 3, &dialog);
        table->setHorizontalHeaderLabels({tr("X"), tr("Y"), tr("Height")});
        QVector<LengthSpinBox*> boxes;
        for (int i = 0; i < points.size(); ++i) {
            for (int c = 0; c < 2; ++c) {
                auto* item = new QTableWidgetItem(formatLength(c == 0 ? points.at(i).x() : points.at(i).y()));
                item->setFlags(item->flags() & ~Qt::ItemIsEditable);
                table->setItem(i, c, item);
            }
            auto* box = new LengthSpinBox(table);
            box->setRange(-10000.0, 10000.0);
            box->setValue(level);
            table->setCellWidget(i, 2, box);
            boxes << box;
        }
        layout->addWidget(table);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        layout->addWidget(buttons);
        if (dialog.exec() != QDialog::Accepted)
            return;
        for (int i = 0; i < boxes.size(); ++i)
            heights[i] = boxes.at(i)->value();
    }
    QJsonArray survey;
    for (int i = 0; i < points.size(); ++i)
        survey.append(QJsonArray{points.at(i).x(), points.at(i).y(), heights.at(i)});
    const QJsonObject r = bridge("create_terrain", {m_levels->activeStorey(),
        QString::fromUtf8(QJsonDocument(survey).toJson(QJsonDocument::Compact)), QString()});
    if (!r.value("ok").toBool()) {
        showError(tr("Terrain"), r.value("error").toString());
        return;
    }
    m_pendingLabel = tr("Terrain");
    afterEdit(r);
    m_pendingLabel.clear();
    m_status->showMessage(tr("Terrain made from %n point(s)", nullptr, int(points.size())));
}

void MainWindow::beamSystemCommand()
{
    QStringList names, guids;
    for (const auto& v : bridge("beam_types").value("types").toArray()) {
        names << v.toObject().value("name").toString();
        guids << v.toObject().value("guid").toString();
    }
    if (guids.isEmpty()) {
        m_status->showMessage(tr("There is no beam type yet"));
        return;
    }
    int type = 0;
    double spacing = 0.4, angle = 0.0;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Beam system"));
        auto* form = new QFormLayout(&dialog);
        auto* kind = new QComboBox(&dialog);
        kind->addItems(names);
        auto* gap = new LengthSpinBox(&dialog);
        gap->setRange(0.1, 20.0);
        gap->setValue(spacing);
        auto* turn = new QDoubleSpinBox(&dialog);
        turn->setRange(-180, 180);
        turn->setSuffix(tr(" degrees"));
        form->addRow(tr("Beam type:"), kind);
        form->addRow(tr("Spacing:"), gap);
        form->addRow(tr("Direction from +X:"), turn);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        type = kind->currentIndex();
        spacing = gap->value();
        angle = turn->value();
    }
    const QString typeGuid = guids.at(type);
    pickPoints(2, true, {tr("Beam system: click a corner of the area"), tr("Beam system: click the opposite corner (Esc cancels)")},
        [this, typeGuid, spacing, angle](const QVector<QPointF>& p, const QString&) {
            const QPointF a = p.at(0), b = p.at(1);
            const QJsonArray outline{QJsonArray{a.x(), a.y()}, QJsonArray{b.x(), a.y()}, QJsonArray{b.x(), b.y()},
                QJsonArray{a.x(), b.y()}};
            const QJsonObject r = bridge("create_beam_system", {m_levels->activeStorey(), typeGuid,
                QString::fromUtf8(QJsonDocument(outline).toJson(QJsonDocument::Compact)), QString::number(spacing, 'g', 17),
                QString::number(angle, 'g', 17), QString()});
            if (!r.value("ok").toBool()) {
                showError(tr("Beam system"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Beam system");
            afterEdit(r);
            m_pendingLabel.clear();
            m_status->showMessage(tr("%n beam(s) added", nullptr, r.value("count").toInt()));
        });
}

void MainWindow::finishCommand(const QString& kind)
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select one or more rooms first"));
        return;
    }
    QString thickness, height;
    if (!m_quiet) {
        bool ok = false;
        const double t = askLength(this, tr("Finish"), tr("Thickness:"), kind == QLatin1String("floor") ? 0.02 : 0.015,
            0.001, 0.5, &ok);
        if (!ok)
            return;
        thickness = QString::number(t, 'g', 17);
        if (kind == QLatin1String("skirting")) {
            const double h = askLength(this, tr("Skirting"), tr("Height:"), 0.1, 0.01, 1.0, &ok);
            if (!ok)
                return;
            height = QString::number(h, 'g', 17);
        }
    }
    const QJsonObject r = bridge("finish_rooms",
        {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact)), kind,
            thickness, height});
    if (!r.value("ok").toBool()) {
        showError(tr("Finish"), r.value("error").toString());
        return;
    }
    afterEdit(r);
    const int failed = int(r.value("failed").toArray().size());
    m_status->showMessage(failed ? tr("%n finish(es) made; some of the selection are not rooms", nullptr,
                                       int(r.value("guids").toArray().size()))
                                 : tr("%n finish(es) made", nullptr, int(r.value("guids").toArray().size())));
}

void MainWindow::shaftCommand()
{
    pickPoints(2, true, {tr("Shaft: click a corner"), tr("Shaft: click the opposite corner (Esc cancels)")},
        [this](const QVector<QPointF>& p, const QString&) {
            const QPointF a = p.at(0), b = p.at(1);
            if (std::abs(b.x() - a.x()) < 0.01 || std::abs(b.y() - a.y()) < 0.01) {
                m_status->showMessage(tr("Shaft: the corners must differ in X and Y"));
                return;
            }
            const QString bottom = m_levels->activeStorey();
            double base = m_levels->activeElevation();
            QStringList names, guids;
            for (const auto& v : bridge("storeys").value("storeys").toArray()) {
                const QJsonObject s = v.toObject();
                if (s.value("model").toBool() || s.value("elevation").toDouble() < base - 1e-6)
                    continue;
                names << s.value("name").toString();
                guids << s.value("guid").toString();
            }
            if (guids.isEmpty())
                return;
            int index = int(guids.size()) - 1; // up to the top by default
            if (!m_quiet && guids.size() > 1) {
                bool ok = false;
                const QString name = QInputDialog::getItem(this, tr("Shaft"), tr("Up to level:"), names, index, false, &ok);
                if (!ok)
                    return;
                index = int(names.indexOf(name));
            }
            const QJsonArray outline{QJsonArray{a.x(), a.y()}, QJsonArray{b.x(), a.y()}, QJsonArray{b.x(), b.y()},
                QJsonArray{a.x(), b.y()}};
            const QJsonObject r = bridge("create_shaft", {QString::fromUtf8(QJsonDocument(outline).toJson(QJsonDocument::Compact)),
                bottom, guids.at(index)});
            if (!r.value("ok").toBool()) {
                showError(tr("Shaft"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Shaft");
            afterEdit(r);
            m_pendingLabel.clear();
            m_status->showMessage(tr("Shaft cut through %n slab(s)", nullptr, int(r.value("slabs").toArray().size())));
        });
}

void MainWindow::mepCommand(const QString& kind)
{
    const QString title = kind == QLatin1String("duct") ? tr("Duct") : kind == QLatin1String("pipe") ? tr("Pipe") : tr("Cable tray");
    double width = kind == QLatin1String("pipe") ? 0.1 : 0.4, height = 0.25, elevation = 2.6;
    QString system;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(title);
        auto* form = new QFormLayout(&dialog);
        auto box = [&](double value) {
            auto* b = new LengthSpinBox(&dialog);
            b->setRange(0.005, 50.0);
            b->setValue(value);
            return b;
        };
        auto* w = box(width);
        auto* h = box(height);
        auto* e = box(elevation);
        auto* sys = new QComboBox(&dialog);
        sys->setEditable(true);
        for (const auto& v : bridge("mep_systems").value("systems").toArray())
            sys->addItem(v.toObject().value("name").toString());
        sys->setCurrentText(QString());
        sys->lineEdit()->setPlaceholderText(tr("%1 system").arg(title));
        form->addRow(kind == QLatin1String("pipe") ? tr("Diameter:") : tr("Width:"), w);
        if (kind != QLatin1String("pipe"))
            form->addRow(tr("Height:"), h);
        form->addRow(tr("Centreline above the level:"), e);
        form->addRow(tr("System:"), sys);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        width = w->value();
        height = h->value();
        elevation = e->value();
        system = sys->currentText().trimmed();
    }
    // The run's points, then segments with an elbow at each bend, in one system, as one undo step.
    pickPoints(-2, false, {tr("Click where the run starts"), tr("Click the next point of the run; Enter finishes, Esc cancels")},
        [this, kind, width, height, elevation, system, title](const QVector<QPointF>& p, const QString&) {
            QJsonArray points;
            for (const QPointF& q : p)
                points.append(QJsonArray{q.x(), q.y()});
            auto num = [](double v) { return QString::number(v, 'g', 17); };
            const QJsonObject r = bridge("create_mep_run", {m_levels->activeStorey(), kind,
                QString::fromUtf8(QJsonDocument(points).toJson(QJsonDocument::Compact)), num(elevation), num(width),
                num(height), system});
            if (!r.value("ok").toBool()) {
                showError(tr("MEP run"), r.value("error").toString());
                return;
            }
            m_pendingLabel = title;
            afterEdit(r);
            m_pendingLabel.clear();
            m_status->showMessage(tr("%1: %2 segment(s), %3 fitting(s) in %4").arg(title)
                .arg(r.value("segments").toArray().size()).arg(r.value("fittings").toArray().size())
                .arg(r.value("system").toString()));
        });
}

// The Model menu had grown to some sixty commands in one list: group them by what they work on.
// Tools and anything not listed here stay at the top; actions keep their object names (shortcuts,
// tests and the command search find them wherever they are).
void MainWindow::groupModelMenu()
{
    QMenu* model = nullptr;
    for (QAction* top : m_menuBar->actions())
        if (top->menu() && top->menu()->title() == tr("&Model"))
            model = top->menu();
    if (!model)
        return;
    struct Group {
        QString title;
        const char* name;
        QStringList actions;
    };
    const QList<Group> groups{
        {tr("&Walls, slabs and openings"), "modelMenuElements",
            {"actionWallHeight", "actionFlipWalls", "actionSaveWallProfile", "actionTrimToRoof", "actionReleaseFromRoof",
                "actionSlabFromWalls", "actionAddSlabEdge", "actionSlabSlope", "actionCeiling", "actionWallOpening",
                "actionOpeningSize", "actionSkylight", "actionCornerWindow", "actionCurtainWallSettings",
                "actionGridSystem", "actionShaft", "actionBeamSystem", "actionLintels", "actionSills", "actionReveals", "actionWallHandrail"}},
        {tr("&Finishes"), "modelMenuFinishes", {"actionFloorFinish", "actionSkirting", "actionWallFinish"}},
        {tr("&Massing and form"), "modelMenuMassing", {"actionMassingBox", "actionPushPull", "actionVisualScripts", "actionVisualGraph"}},
        {tr("&Site"), "modelMenuSite", {"actionTerrain", "actionTerrainPoints", "actionBuildingPad", "actionKerb", "actionRoadMarking", "actionPlantingArea"}},
        {tr("&Annotation and 2D"), "modelMenuAnnotation",
            {"actionTagAll", "actionInteriorElevations", "actionAreaLabel", "actionDetailOnly", "actionDetailOnlyClear", "actionAutoDimension", "actionOverallDimension", "actionGridDimension", "actionKeynotes",
                "actionFillFromShape", "actionMake2DBlock", "actionInsert2DBlock"}},
        {tr("&Types, models and library"), "modelMenuTypes",
            {"actionTypeManager", "actionPurgeTypes", "actionClassifications", "actionUpdateModelInstances",
                "actionExplodeInstance", "actionEditInPlace", "actionFinishInPlace", "actionSaveModelToLibrary",
                "actionLoadModelFromLibrary", "actionUpdateLibraryObjects", "actionCustomiseObjectCopy"}},
        {tr("&Links"), "modelMenuLinks", {"actionLinks", "actionMeshLink"}},
        {tr("A&nalysis and checking"), "modelMenuAnalysis",
            {"actionCheckModel", "actionIssues", "actionEnergyReport", "actionCostEstimate",
                "actionConstructionSequence", "actionAIVisualiser"}},
    };
    model->addSeparator();
    for (const Group& g : groups) {
        QMenu* sub = nullptr;
        for (const QString& name : g.actions) {
            QAction* a = findChild<QAction*>(name);
            if (!a || !model->actions().contains(a))
                continue;
            if (!sub) {
                sub = model->addMenu(g.title);
                sub->setObjectName(QLatin1String(g.name));
            }
            model->removeAction(a);
            sub->addAction(a);
        }
    }
    // separators left back to back by the moves
    QAction* previous = nullptr;
    for (QAction* a : model->actions()) {
        if (a->isSeparator() && (!previous || previous->isSeparator()))
            model->removeAction(a);
        else
            previous = a;
    }
}

QMenu* MainWindow::buildViewContextMenu()
{
    auto* menu = new QMenu(this);
    menu->setObjectName(QStringLiteral("viewContextMenu"));
    auto add = [this, menu](const char* name) {
        if (QAction* a = findChild<QAction*>(QLatin1String(name)); a && a->isVisible())
            menu->addAction(a);
    };
    if (m_lastCommand) {
        m_repeatLast->setText(tr("&Repeat \"%1\"").arg(commandText(m_lastCommand)));
        menu->addAction(m_repeatLast);
        menu->addSeparator();
    }
    if (!m_selection.isEmpty()) {
        for (const char* name : {"actionShowProperties", "actionZoomToSelection"})
            add(name);
        menu->addSeparator();
        for (const char* name : {"actionMoveTool", "actionRotateTool", "actionMirror", "actionDuplicate",
                 "actionCopy", "actionCopyToLevel", "actionElevate", "actionAlign", "actionOffset", "actionMultiply"})
            add(name);
        menu->addSeparator();
        for (const char* name : {"actionSelectSimilar", "actionSelectClass", "actionHideSelected", "actionIsolateSelected"})
            add(name);
        menu->addSeparator();
        for (const char* name : {"actionGroup", "actionUngroup", "actionLock", "actionUnlock", "actionPickUp", "actionInject"})
            add(name);
        menu->addSeparator();
        add("actionDelete");
    } else {
        for (const char* name : {"actionPaste", "actionShowAll", "actionFitAll", "actionSelectAll"})
            add(name);
    }
    menu->addSeparator();
    add("actionSearchCommands");
    return menu;
}

void MainWindow::noteCommand(QAction* action)
{
    if (!action || !action->objectName().startsWith(QLatin1String("action")))
        return;
    if (action->objectName() != QLatin1String("actionRepeatLast") && repeatable(action)) {
        m_lastCommand = action;
        m_repeatLast->setText(tr("&Repeat \"%1\"").arg(commandText(action)));
        m_repeatLast->setEnabled(true);
    }
    if (action == m_undo || action == m_redo)
        return;
    m_pendingLabel = commandText(action);
    m_pendingLabel.remove(QStringLiteral("..."));
    m_pendingLabel = m_pendingLabel.trimmed();
    // The label is for the edit this command makes, even after its dialog: it is dropped when the
    // event loop is back with no dialog open.
    if (!m_pendingTimer) {
        m_pendingTimer = new QTimer(this);
        m_pendingTimer->setSingleShot(true);
        connect(m_pendingTimer, &QTimer::timeout, this, [this] {
            if (QApplication::activeModalWidget())
                m_pendingTimer->start(50); // still in the command's dialog
            else
                m_pendingLabel.clear();
        });
    }
    m_pendingTimer->start(0);
}

void MainWindow::runCommand(QAction* action)
{
    if (!action || !action->isEnabled())
        return;
    noteCommand(action);
    action->trigger();
}

void MainWindow::showCommandSearch()
{
    CommandSearchDialog dialog(this, this);
    if (dialog.exec() == QDialog::Accepted && dialog.chosen())
        runCommand(dialog.chosen());
}

void MainWindow::refreshUndoHistory()
{
    if (!m_undoPanel)
        return;
    const QJsonObject h = bridge("undo_history");
    QStringList undo, redo;
    for (const auto& v : h.value("undo").toArray())
        undo << v.toString();
    for (const auto& v : h.value("redo").toArray())
        redo << v.toString();
    const int maxId = h.value("max_id").toInt();
    if (maxId > m_seenStepId && !undo.isEmpty() && redo.isEmpty()) { // a step not seen before: name it
        QString label = m_pendingLabel;
        if (label.isEmpty() && m_tool != Tool::None)
            if (QAction* tool = m_toolActions.value(int(m_tool)))
                label = commandText(tool);
        if (!label.isEmpty() && bridge("label_last_step", {label}).value("ok").toBool())
            undo.last() = label;
    }
    m_seenStepId = maxId;
    m_undoPanel->setHistory(undo, redo);
}

void MainWindow::jumpInHistory(int steps)
{
    if (steps == 0)
        return;
    const QJsonObject r = bridge(steps < 0 ? "undo_steps" : "redo_steps", {QString::number(std::abs(steps))});
    if (!r.value("ok").toBool())
        return;
    afterEdit(r);
    refreshLibraryListing();
}

void MainWindow::nudgeSelection(int dx, int dy, bool coarse)
{
    if (m_selection.isEmpty())
        return;
    const double step = coarse ? 0.1 : 0.01; // 10 mm, Shift 100 mm
    m_pendingLabel = tr("Nudge");
    if (moveSelection(QPointF(dx * step, dy * step)))
        m_status->showMessage(tr("Moved %1").arg(formatLength(step)), 1500);
    m_pendingLabel.clear();
}

bool MainWindow::openDroppedFiles(const QStringList& paths)
{
    bool any = false;
    for (const QString& path : paths) {
        const QString kind = dropKind(path);
        if (kind == QLatin1String("open")) {
            any = openPath(path) || any;
            break; // one project at a time
        }
        if (kind == QLatin1String("underlay"))
            placeUnderlayDialog(path);
        else if (kind == QLatin1String("mesh"))
            importMeshDialog(path);
        else if (kind == QLatin1String("cloud"))
            importPointCloudDialog(path);
        else
            continue;
        any = true;
    }
    if (!any)
        m_status->showMessage(tr("NicBim cannot open that file"), 3000);
    return any;
}

void MainWindow::dragEnterEvent(QDragEnterEvent* event)
{
    for (const QUrl& url : event->mimeData()->urls())
        if (url.isLocalFile() && !dropKind(url.toLocalFile()).isEmpty()) {
            event->acceptProposedAction();
            return;
        }
    QMainWindow::dragEnterEvent(event);
}

void MainWindow::dropEvent(QDropEvent* event)
{
    QStringList paths;
    for (const QUrl& url : event->mimeData()->urls())
        if (url.isLocalFile())
            paths << url.toLocalFile();
    if (paths.isEmpty())
        return QMainWindow::dropEvent(event);
    event->acceptProposedAction();
    // After the drop returns: the dialogs it opens must not run inside the drag-and-drop loop.
    QTimer::singleShot(0, this, [this, paths] { openDroppedFiles(paths); });
}

bool MainWindow::printSheet(const QString& number, QPrinter* printer)
{
    const QJsonObject sheet = bridgeInBackground("sheet_svg", {number},
        tr("Composing sheet %1...\nLarge sheets can take a minute.").arg(number));
    QString error;
    if (!sheet.value("ok").toBool()
        || !printSvg(sheet.value("svg").toString().toUtf8(), sheet.value("width").toDouble(),
            sheet.value("height").toDouble(), printer, &error)) {
        showError(tr("Could not print the sheet"), error.isEmpty() ? sheet.value("error").toString() : error);
        return false;
    }
    return true;
}

void MainWindow::printSheetDialog()
{
    QString number = m_sheetsPanel->selectedSheet();
    if (auto* view = qobject_cast<DrawingView*>(m_dock->view(m_dock->current())); view && view->guid().startsWith(QLatin1String("sheet:")))
        number = view->guid().mid(6);
    if (number.isEmpty()) {
        showError(tr("No sheet"), tr("Add a sheet in the Sheets panel first."));
        return;
    }
    QPrinter printer(QPrinter::HighResolution);
    printer.setDocName(tr("Sheet %1").arg(number));
    QPrintPreviewDialog preview(&printer, this);
    preview.setWindowTitle(tr("Print sheet %1").arg(number));
    connect(&preview, &QPrintPreviewDialog::paintRequested, this, [this, number](QPrinter* p) { printSheet(number, p); });
    preview.exec();
}

// ---------------------------------------------------------------- clicking points instead of typing them

void MainWindow::pickPoints(int count, bool rectangle, const QStringList& hints, PointPick::Done done)
{
    setTool(Tool::None);
    m_pick = std::make_shared<PointPick>();
    m_pick->count = rectangle ? 2 : count < 0 ? 0 : std::max(1, count);
    m_pick->minimum = count < 0 ? -count : m_pick->count;
    m_pick->rectangle = rectangle;
    m_pick->hints = hints;
    m_pick->done = std::move(done);
    Snapper& s = m_pick->snapper;
    s.setWalls(m_twoPointTool->snapper().walls());
    s.setGridLines(m_twoPointTool->snapper().gridLines());
    s.setPoints(m_twoPointTool->snapper().points());
    s.setUnderlays(m_underlaySnap);
    m_viewport->setDrawingMode(true, m_levels->activeElevation());
    m_viewport->setFocus();
    m_status->showMessage(hints.value(0));
}

void MainWindow::cancelPick()
{
    if (!m_pick)
        return;
    m_pick.reset();
    m_viewport->setToolOverlay({});
    m_viewport->setDrawingMode(false);
    m_status->showMessage(tr("Cancelled"), 2000);
}

void MainWindow::pickPointMoved(QPointF p, double tolerance, Qt::KeyboardModifiers mods)
{
    if (!m_pick)
        return;
    const bool ortho = bool(mods & Qt::ShiftModifier) != m_orthoLock;
    const QPointF* from = m_pick->points.isEmpty() ? nullptr : &m_pick->points.last();
    const QPointF q = m_pick->snapper.snap(p, tolerance, from, ortho).point;
    const double z = m_levels->activeElevation();
    QVector<MeasurePoint> path;
    QString label;
    if (m_pick->rectangle && !m_pick->points.isEmpty()) {
        const QPointF a = m_pick->points.first();
        for (const QPointF& c : {a, QPointF(q.x(), a.y()), q, QPointF(a.x(), q.y()), a})
            path.push_back({c.x(), c.y(), z});
        label = formatLength(std::abs(q.x() - a.x())) + QStringLiteral(" × ") + formatLength(std::abs(q.y() - a.y()));
    } else {
        for (const QPointF& c : m_pick->points)
            path.push_back({c.x(), c.y(), z});
        path.push_back({q.x(), q.y(), z});
    }
    m_viewport->setToolOverlay(new MeasureOverlay(path, label));
    m_status->showMessage(m_pick->hints.value(std::min(int(m_pick->points.size()), int(m_pick->hints.size()) - 1)));
}

void MainWindow::pickPointAt(QPointF p, double tolerance, Qt::KeyboardModifiers mods)
{
    if (!m_pick)
        return;
    const bool ortho = bool(mods & Qt::ShiftModifier) != m_orthoLock;
    const QPointF* from = m_pick->points.isEmpty() ? nullptr : &m_pick->points.last();
    const Snap s = m_pick->snapper.snap(p, tolerance, from, ortho);
    m_pick->points.push_back(s.point);
    m_pick->wall = s.wallGuid;
    if (m_pick->count == 0 || m_pick->points.size() < m_pick->count) {
        m_status->showMessage(m_pick->hints.value(std::min(int(m_pick->points.size()), int(m_pick->hints.size()) - 1)));
        return;
    }
    finishPick();
}

void MainWindow::finishPick()
{
    if (!m_pick || m_pick->points.size() < m_pick->minimum)
        return;
    const std::shared_ptr<PointPick> pick = std::move(m_pick);
    m_viewport->setToolOverlay({});
    m_viewport->setDrawingMode(false);
    pick->done(pick->points, pick->wall);
}

void MainWindow::massingBoxCommand()
{
    bool ok = true;
    const double height = m_quiet ? 12.0 : askLength(this, tr("Massing box"), tr("Height of the box:"), 12.0, 0.1, 1000.0, &ok);
    if (!ok)
        return;
    pickPoints(2, true, {tr("Massing box: click a corner"), tr("Massing box: click the opposite corner (Esc cancels)")},
        [this, height](const QVector<QPointF>& p, const QString&) {
            const QPointF a = p.at(0), b = p.at(1);
            const double w = std::abs(b.x() - a.x()), d = std::abs(b.y() - a.y());
            if (w < 0.01 || d < 0.01) {
                m_status->showMessage(tr("Massing box: the corners must differ in X and Y"));
                return;
            }
            auto num = [](double v) { return QString::number(v, 'g', 17); };
            const QJsonObject r = bridge("create_massing", {m_levels->activeStorey(), num((a.x() + b.x()) / 2),
                num((a.y() + b.y()) / 2), num(w), num(d), num(height), tr("Massing")});
            if (!r.value("ok").toBool()) {
                showError(tr("Massing box"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Massing box");
            afterEdit(r);
            m_pendingLabel.clear();
            m_viewport->selectGuids({r.value("guid").toString()});
            setSelection({r.value("guid").toString()});
            m_status->showMessage(tr("Massing box added"));
        });
}

void MainWindow::insertBlockCommand()
{
    QStringList names;
    for (const auto& v : bridge("blocks").value("blocks").toArray())
        names << v.toObject().value("name").toString();
    if (names.isEmpty()) {
        m_status->showMessage(tr("No 2D blocks yet: save one with Create 2D block"));
        return;
    }
    bool ok = true;
    const QString name = m_quiet || names.size() == 1 ? names.first()
        : QInputDialog::getItem(this, tr("Insert 2D block"), tr("Block:"), names, 0, false, &ok);
    if (!ok || name.isEmpty())
        return;
    pickPoints(1, false, {tr("Insert 2D block \"%1\": click where it goes (Esc cancels)").arg(name)},
        [this, name](const QVector<QPointF>& p, const QString&) {
            const QJsonObject r = bridge("insert_block", {name, m_levels->activeStorey(),
                QString::number(p.at(0).x(), 'g', 17), QString::number(p.at(0).y(), 'g', 17), QStringLiteral("0"),
                QStringLiteral("1")});
            if (!r.value("ok").toBool()) {
                showError(tr("Insert 2D block"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Insert 2D block");
            afterEdit(r);
            m_pendingLabel.clear();
            QStringList inserted;
            for (const auto& v : r.value("guids").toArray())
                inserted << v.toString();
            m_viewport->selectGuids(inserted);
            setSelection(inserted);
            m_status->showMessage(tr("2D block \"%1\" inserted").arg(name));
        });
}

void MainWindow::skylightCommand()
{
    if (m_selection.size() != 1) {
        m_status->showMessage(tr("Select one slab first: the skylight goes in it"));
        return;
    }
    const QString slab = m_selection.first();
    double width = 1.2, depth = 1.2;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Skylight"));
        auto* form = new QFormLayout(&dialog);
        auto spin = [&](double value) {
            auto* box = new LengthSpinBox(&dialog);
            box->setRange(0.1, 50.0);
            box->setValue(value);
            return box;
        };
        auto* w = spin(width);
        auto* d = spin(depth);
        form->addRow(tr("Width:"), w);
        form->addRow(tr("Depth:"), d);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        width = w->value();
        depth = d->value();
    }
    pickPoints(1, false, {tr("Skylight: click its centre in the slab (Esc cancels)")},
        [this, slab, width, depth](const QVector<QPointF>& p, const QString&) {
            auto num = [](double v) { return QString::number(v, 'g', 17); };
            const QJsonObject r = bridge("create_skylight", {slab, num(p.at(0).x() - width / 2),
                num(p.at(0).y() - depth / 2), num(width), num(depth), QString()});
            if (!r.value("ok").toBool()) {
                showError(tr("Skylight"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Skylight");
            afterEdit(r);
            m_pendingLabel.clear();
            m_viewport->selectGuids({r.value("guid").toString()});
            setSelection({r.value("guid").toString()});
            m_status->showMessage(tr("Skylight added"));
        });
}

void MainWindow::wallOpeningDialog()
{
    double width = 0.9, height = 2.1, sill = 0.0;
    if (!m_quiet) {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("Wall opening"));
        auto* form = new QFormLayout(&dialog);
        auto box = [&](double lo, double value) {
            auto* b = new LengthSpinBox(&dialog);
            b->setRange(lo, 100.0);
            b->setValue(value);
            return b;
        };
        auto* w = box(0.01, width);
        auto* h = box(0.01, height);
        auto* s = box(0.0, sill);
        form->addRow(tr("Width:"), w);
        form->addRow(tr("Height:"), h);
        form->addRow(tr("Sill above the base:"), s);
        auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
        form->addRow(buttons);
        connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
        if (dialog.exec() != QDialog::Accepted)
            return;
        width = w->value();
        height = h->value();
        sill = s->value();
    }
    pickPoints(1, false, {tr("Wall opening: click its centre on a wall (Esc cancels)")},
        [this, width, height, sill](const QVector<QPointF>& p, const QString& wallGuid) {
            QString wall = wallGuid;
            if (wall.isEmpty() && m_selection.size() == 1)
                wall = m_selection.first();
            const QVector<SnapWall> walls = m_twoPointTool->snapper().walls();
            const auto it = std::find_if(walls.begin(), walls.end(), [&](const SnapWall& w) { return w.guid == wall; });
            if (it == walls.end()) {
                m_status->showMessage(tr("Wall opening: click on a wall"));
                return;
            }
            const QPointF axis = it->b - it->a;
            const double length = std::hypot(axis.x(), axis.y());
            if (length < 1e-9)
                return;
            const QPointF d = p.at(0) - it->a;
            const double along = (d.x() * axis.x() + d.y() * axis.y()) / length;
            auto num = [](double v) { return QString::number(v, 'g', 17); };
            const QJsonObject r = bridge("create_wall_opening", {wall, num(along), num(width), num(height), num(sill)});
            if (!r.value("ok").toBool()) {
                showError(tr("Wall opening"), r.value("error").toString());
                return;
            }
            m_pendingLabel = tr("Wall opening");
            afterEdit(r);
            m_pendingLabel.clear();
            setSelection({r.value("guid").toString()});
            m_status->showMessage(tr("Wall opening created"));
        });
}

void MainWindow::pushPullCommand()
{
    if (m_selection.size() != 1) {
        m_status->showMessage(tr("Select one massing box or mesh to push/pull"));
        return;
    }
    setTool(Tool::None);
    m_pushPullPick = true;
    m_viewport->setFacePickMode(true);
    m_viewport->setFocus();
    m_status->showMessage(tr("Push/pull: click the face to move (Esc cancels)"));
}

bool MainWindow::pushPullFace(const QString& face, double distance)
{
    if (m_selection.size() != 1)
        return false;
    const QJsonObject r = bridge("push_pull", {m_selection.first(), face, QString::number(distance, 'g', 17)});
    if (!r.value("ok").toBool()) {
        showError(tr("Push/pull"), r.value("error").toString());
        return false;
    }
    m_pendingLabel = tr("Push/pull");
    afterEdit(r);
    m_pendingLabel.clear();
    m_status->showMessage(tr("Face %1 moved %2").arg(face, formatLength(distance)));
    return true;
}

void MainWindow::connectPickSignals()
{
    onEachView([this](Viewport* v) {
        connect(v, &Viewport::workPointMoved, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
            pickPointMoved(p, tolerance, mods);
        });
        connect(v, &Viewport::workPointClicked, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
            pickPointAt(p, tolerance, mods);
        });
        connect(v, &Viewport::drawingConfirmed, this, [this] { // Enter or a double click
            if (m_pick && m_pick->count == 0)
                finishPick();
        });
        connect(v, &Viewport::drawingEnded, this, [this, v] {
            if (m_pick)
                cancelPick();
            if (m_pushPullPick) {
                m_pushPullPick = false;
                v->setFacePickMode(false);
                m_status->showMessage(tr("Cancelled"), 2000);
            }
        });
        connect(v, &Viewport::facePicked, this, [this, v](double, double, double, double nx, double ny, double nz) {
            if (!m_pushPullPick)
                return;
            m_pushPullPick = false;
            v->setFacePickMode(false);
            const QString face = faceFromNormal(nx, ny, nz);
            bool ok = true;
            const double distance = m_quiet ? 1.0
                : askLength(this, tr("Push/pull"), tr("Move face %1 by (negative pulls inward):").arg(face), 1.0,
                    -1000.0, 1000.0, &ok);
            if (ok)
                pushPullFace(face, distance);
        });
    });
}

} // namespace kimbim
