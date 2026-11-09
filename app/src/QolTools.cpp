// SPDX-License-Identifier: GPL-3.0-or-later
// Everyday conveniences: the view's right-click menu, command search, Repeat last command, the Undo
// history panel and step labels, nudging with the arrow keys, object-snap and ortho toggles, dropped
// files and printing sheets.
#include "QolTools.h"

#include "DockLayout.h"
#include "DrawingView.h"
#include "MainWindow.h"
#include "SheetExport.h"
#include "SheetsPanel.h"
#include "Snapper.h"
#include "StatusStrip.h"
#include "Viewport.h"

#include <QAbstractButton>
#include <QAction>
#include <QApplication>
#include <QDragEnterEvent>
#include <QDropEvent>
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

QString dropKind(const QString& path)
{
    const QFileInfo info(path);
    if (info.isDir())
        return QStringLiteral("open");
    const QString suffix = info.suffix().toLower();
    if (suffix == QLatin1String("kim") || suffix == QLatin1String("ifc"))
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
    if (m_viewMenu) {
        m_viewMenu->addSeparator();
        m_viewMenu->addAction(m_objectSnaps);
        m_viewMenu->addAction(m_orthoAction);
    }
    m_status->addToggle(m_objectSnaps);
    m_status->addToggle(m_orthoAction);

    QAction* print = new QAction(tr("&Print sheet..."), this);
    print->setObjectName(QStringLiteral("actionPrintSheet"));
    print->setShortcut(QKeySequence::Print);
    print->setToolTip(tr("Print the open or selected sheet, with a preview"));
    connect(print, &QAction::triggered, this, &MainWindow::printSheetDialog);
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
    setAcceptDrops(true);
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
    auto clear = std::make_shared<std::function<void()>>();
    *clear = [this, clear, token = ++m_pendingToken] {
        if (token != m_pendingToken)
            return;
        if (QApplication::activeModalWidget()) {
            QTimer::singleShot(50, this, *clear);
            return;
        }
        m_pendingLabel.clear();
    };
    QTimer::singleShot(0, this, *clear);
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

} // namespace kimbim
