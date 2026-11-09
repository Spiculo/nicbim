// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// Everyday conveniences around the main window: command search, the Undo history panel, which
// command an edit came from (for its undo label and Repeat last command), and dropped files.

#include <QDialog>
#include <QList>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QWidget>

#include <functional>

class QAction;
class QLineEdit;
class QListWidget;
class QListWidgetItem;

namespace kimbim {

// The text of a menu command without its mnemonic ("&Massing box..." -> "Massing box...").
QString commandText(const QAction* action);

// One command of the menu bar, with the menus it lives in ("Model > Wall junctions").
struct CommandEntry {
    QString path;
    QString text;
    QString keys;
    QAction* action = nullptr;
};

// Every command of `window`'s menu bar (submenus walked, separators and placeholders skipped), in
// menu order. Disabled commands are included: the search shows them greyed out.
QList<CommandEntry> collectCommands(QWidget* window);

// The commands whose text or menu path holds every word of `query` (case and accents ignored),
// commands whose text starts with the query first. An empty query keeps them all.
QList<CommandEntry> filterCommands(const QList<CommandEntry>& commands, const QString& query);

// Search commands (Ctrl+K): type part of a command's name, Enter runs the highlighted one.
class CommandSearchDialog : public QDialog {
    Q_OBJECT
public:
    explicit CommandSearchDialog(QWidget* window, QWidget* parent = nullptr);
    QLineEdit* search() const { return m_search; }
    QListWidget* list() const { return m_list; }
    QAction* chosen() const { return m_chosen; } // after accept(): the command to run

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void refill(const QString& query);
    void choose(QListWidgetItem* item);

    QList<CommandEntry> m_commands;
    QLineEdit* m_search = nullptr;
    QListWidget* m_list = nullptr;
    QAction* m_chosen = nullptr;
};

// The Undo history panel: the steps since the file opened, newest last, then the undone ones
// (greyed). Clicking a row undoes or redoes back to just after that step.
class UndoHistoryPanel : public QWidget {
    Q_OBJECT
public:
    explicit UndoHistoryPanel(QWidget* parent = nullptr);
    void setHistory(const QStringList& undo, const QStringList& redo);
    QListWidget* list() const { return m_list; }
    int current() const { return m_current; } // the row of the present state (0 = as opened)

signals:
    // Negative: undo that many steps; positive: redo them.
    void jumpRequested(int steps);

private:
    QListWidget* m_list = nullptr;
    int m_current = 0;
};

// Watches the application for a command being started by the user (its shortcut, a menu click or
// Enter, a toolbar or palette button) and reports it before the command runs.
class CommandTracker : public QObject {
    Q_OBJECT
public:
    explicit CommandTracker(std::function<void(QAction*)> started, QObject* parent = nullptr);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    std::function<void(QAction*)> m_started;
};

// What a dropped file does: "open" (.kim, .ifc, a folder), "underlay" (DXF, DWG, PDF, pictures),
// "mesh", "cloud" (point clouds), or "" (not something NicBim takes).
QString dropKind(const QString& path);

} // namespace kimbim
