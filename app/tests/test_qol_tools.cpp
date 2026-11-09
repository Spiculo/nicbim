// SPDX-License-Identifier: GPL-3.0-or-later
// QolTools.cpp: the view's right-click menu, command search, Repeat last command, the Undo history
// panel, nudging, the object-snap and ortho toggles, dropped files and printing sheets.
#include <QAction>
#include <QFile>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QPrinter>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

#include "MainWindow.h"
#include "QolTools.h"
#include "SheetExport.h"
#include "Snapper.h"
#include "Viewport.h"
#include "WallTool.h"

namespace {

QAction* action(kimbim::MainWindow& w, const char* name)
{
    QAction* a = w.findChild<QAction*>(QString::fromLatin1(name));
    if (!a)
        qFatal("missing action %s", name);
    return a;
}

QString drawWall(kimbim::MainWindow& w, QPointF a = QPointF(0, 0), QPointF b = QPointF(4, 0))
{
    const QStringList before = w.viewport()->guids();
    w.setTool(kimbim::MainWindow::Tool::Wall);
    w.wallTool()->setTolerance(0.05);
    w.wallTool()->click(a);
    w.wallTool()->click(b);
    w.setTool(kimbim::MainWindow::Tool::None);
    for (const QString& g : w.viewport()->guids())
        if (!before.contains(g))
            return g;
    return {};
}

QStringList rows(QListWidget* list)
{
    QStringList out;
    for (int i = 0; i < list->count(); ++i)
        out << list->item(i)->text();
    return out;
}

QStringList actionNames(QMenu* menu)
{
    QStringList out;
    for (QAction* a : menu->actions())
        if (!a->isSeparator())
            out << a->objectName();
    return out;
}

} // namespace

class TestQolTools : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void commandSearchFindsMenuCommandsByWords()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QList<kimbim::CommandEntry> all = kimbim::collectCommands(&w);
        QVERIFY(all.size() > 100);
        auto has = [&](const QList<kimbim::CommandEntry>& list, const char* name) {
            for (const auto& e : list)
                if (e.action->objectName() == QLatin1String(name))
                    return true;
            return false;
        };
        QVERIFY(has(all, "actionMassingBox"));
        const auto massing = kimbim::filterCommands(all, QStringLiteral("massing"));
        QVERIFY(!massing.isEmpty());
        QCOMPARE(massing.first().action->objectName(), QStringLiteral("actionMassingBox"));
        // every word must match; the menu path counts ("model" is the Massing box's menu)
        QVERIFY(has(kimbim::filterCommands(all, QStringLiteral("box model")), "actionMassingBox"));
        QVERIFY(kimbim::filterCommands(all, QStringLiteral("massing zzzz")).isEmpty());
        // accents and case are ignored
        QVERIFY(has(kimbim::filterCommands(all, QStringLiteral("MÁSSING")), "actionMassingBox"));
        QCOMPARE(kimbim::filterCommands(all, QString()).size(), all.size());

        kimbim::CommandSearchDialog dialog(&w);
        dialog.search()->setText(QStringLiteral("fit all"));
        QVERIFY(dialog.list()->count() >= 1);
        QTest::keyClick(dialog.search(), Qt::Key_Return);
        QVERIFY(dialog.chosen());
        QCOMPARE(kimbim::commandText(dialog.chosen()), QStringLiteral("Fit all"));
        QCOMPARE(dialog.result(), int(QDialog::Accepted));
        QVERIFY(action(w, "actionSearchCommands")->shortcuts().contains(QKeySequence(Qt::CTRL | Qt::Key_K)));
    }

    void rightClickMenuOffersCommandsForTheSelection()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        std::unique_ptr<QMenu> empty(w.buildViewContextMenu());
        QVERIFY(actionNames(empty.get()).contains(QStringLiteral("actionShowAll")));
        QVERIFY(!actionNames(empty.get()).contains(QStringLiteral("actionDelete")));
        const QString wall = drawWall(w);
        QVERIFY(!wall.isEmpty());
        w.viewport()->selectGuids({wall});
        w.setSelection({wall});
        std::unique_ptr<QMenu> menu(w.buildViewContextMenu());
        const QStringList names = actionNames(menu.get());
        for (const char* name : {"actionShowProperties", "actionMoveTool", "actionRotateTool", "actionMirror",
                 "actionHideSelected", "actionGroup", "actionLock", "actionDelete", "actionSearchCommands"})
            QVERIFY2(names.contains(QLatin1String(name)), name);
        // the menu's Delete is the Edit menu's own command
        QCOMPARE(menu->actions().last()->objectName(), QStringLiteral("actionSearchCommands"));
        // a right click on an element that is not selected selects it first
        const QString other = drawWall(w, QPointF(0, 3), QPointF(4, 3));
        QSignalSpy spy(w.viewport(), &kimbim::Viewport::contextMenuRequested);
        emit w.viewport()->contextMenuRequested(QPoint(10, 10), other);
        QCOMPARE(w.selection(), QStringList{other});
        for (QMenu* open : w.findChildren<QMenu*>(QStringLiteral("viewContextMenu")))
            open->close();
    }

    void undoHistoryNamesStepsAndJumps()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::UndoHistoryPanel* panel = w.undoHistoryPanel();
        QVERIFY(panel);
        QCOMPARE(panel->list()->count(), 1); // "As opened"
        drawWall(w);
        drawWall(w, QPointF(0, 3), QPointF(4, 3));
        QStringList labels = rows(panel->list());
        QCOMPARE(labels.size(), 3);
        QCOMPARE(labels.at(1), QStringLiteral("Wall")); // drawn with the Wall tool
        QCOMPARE(panel->current(), 2);
        const int walls = w.viewport()->guids().size();
        w.jumpInHistory(-2); // the "As opened" row
        QCOMPARE(panel->current(), 0);
        QCOMPARE(w.viewport()->guids().size(), walls - 2);
        QCOMPARE(panel->list()->count(), 3); // the undone steps stay listed, greyed
        emit panel->jumpRequested(1);
        QCOMPARE(panel->current(), 1);
        QCOMPARE(w.viewport()->guids().size(), walls - 1);
        // a command started by the user names its step
        const QString wall = w.viewport()->guids().last();
        w.viewport()->selectGuids({wall});
        w.setSelection({wall});
        w.runCommand(action(w, "actionLock"));
        labels = rows(panel->list());
        QCOMPARE(labels.size(), 3); // the redo step was replaced by the new one
        QCOMPARE(labels.last(), kimbim::commandText(action(w, "actionLock")).remove(QStringLiteral("...")).trimmed());
    }

    void repeatLastCommandRunsItAgain()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QAction* repeat = action(w, "actionRepeatLast");
        QVERIFY(!repeat->isEnabled());
        QAction* hide = action(w, "actionHideSelected");
        int runs = 0;
        connect(hide, &QAction::triggered, &w, [&runs] { ++runs; });
        w.runCommand(hide);
        QCOMPARE(runs, 1);
        QVERIFY(repeat->isEnabled());
        QCOMPARE(w.lastCommand(), hide);
        repeat->trigger();
        QCOMPARE(runs, 2);
        w.runCommand(action(w, "actionUndo")); // undo is never what Repeat repeats
        QCOMPARE(w.lastCommand(), hide);
        std::unique_ptr<QMenu> menu(w.buildViewContextMenu());
        QCOMPARE(menu->actions().first(), repeat);
    }

    void arrowKeysNudgeTheSelection()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString wall = drawWall(w);
        w.nudgeSelection(1, 0, false); // nothing selected: nothing happens
        QCOMPARE(w.undoHistoryPanel()->current(), 1);
        w.viewport()->selectGuids({wall});
        w.setSelection({wall});
        QSignalSpy spy(w.viewport(), &kimbim::Viewport::nudgeRequested);
        QTest::keyClick(w.viewport(), Qt::Key_Right, Qt::ShiftModifier);
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().at(0).toInt(), 1);
        QCOMPARE(spy.first().at(2).toBool(), true);
        QCOMPARE(w.undoHistoryPanel()->current(), 2);
        QCOMPARE(rows(w.undoHistoryPanel()->list()).last(), QStringLiteral("Nudge"));
    }

    void snapAndOrthoToggles()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QAction* snaps = action(w, "actionObjectSnaps");
        QAction* ortho = action(w, "actionOrthoLock");
        QCOMPARE(snaps->shortcut(), QKeySequence(Qt::Key_F3));
        QCOMPARE(ortho->shortcut(), QKeySequence(Qt::Key_F8));
        QVERIFY(snaps->isChecked());
        kimbim::Snapper snapper;
        snapper.setWalls({kimbim::SnapWall{QStringLiteral("w"), QPointF(0, 0), QPointF(4, 0)}});
        QCOMPARE(snapper.snap(QPointF(0.03, 0.02), 0.1).kind, kimbim::Snap::Endpoint);
        snaps->setChecked(false);
        QVERIFY(!kimbim::Snapper::objectSnapsEnabled());
        QVERIFY(snapper.snap(QPointF(0.03, 0.02), 0.1).kind != kimbim::Snap::Endpoint);
        QCOMPARE(snapper.snap(QPointF(0.03, 0.02), -1).point, QPointF(0.03, 0.02)); // a typed point stays exact
        snaps->setChecked(true);
        QVERIFY(!w.orthoLocked());
        ortho->setChecked(true);
        QVERIFY(w.orthoLocked());
        ortho->setChecked(false);
    }

    void droppedFilesGoWhereTheyBelong()
    {
        QCOMPARE(kimbim::dropKind(QStringLiteral("a/House.IFC")), QStringLiteral("open"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("a/House.kim")), QStringLiteral("open"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("survey.dwg")), QStringLiteral("underlay"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("scan.jpg")), QStringLiteral("underlay"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("chair.glb")), QStringLiteral("mesh"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("site.laz")), QStringLiteral("cloud"));
        QCOMPARE(kimbim::dropKind(QStringLiteral("notes.docx")), QString());

        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QTemporaryDir dir;
        const QString ifc = dir.filePath(QStringLiteral("dropped.ifc"));
        QVERIFY(w.saveAs(ifc));
        QVERIFY(!w.openDroppedFiles({dir.filePath(QStringLiteral("notes.docx"))}));
        QVERIFY(w.newProject());
        QVERIFY(w.openDroppedFiles({ifc}));
        QVERIFY(w.acceptDrops());
    }

    void sheetsPrintToAPdfPrinter()
    {
        const QByteArray svg = "<svg xmlns='http://www.w3.org/2000/svg' width='420mm' height='297mm' "
                               "viewBox='0 0 420 297'><rect x='10' y='10' width='400' height='277' "
                               "fill='none' stroke='black'/></svg>";
        QTemporaryDir dir;
        QPrinter printer(QPrinter::HighResolution);
        printer.setOutputFormat(QPrinter::PdfFormat);
        printer.setOutputFileName(dir.filePath(QStringLiteral("sheet.pdf")));
        QString error;
        QVERIFY2(kimbim::printSvg(svg, 420, 297, &printer, &error), qPrintable(error));
        QCOMPARE(printer.pageLayout().orientation(), QPageLayout::Landscape);
        QFile pdf(dir.filePath(QStringLiteral("sheet.pdf")));
        QVERIFY(pdf.open(QIODevice::ReadOnly));
        QVERIFY(pdf.read(4) == "%PDF");
        QVERIFY(!kimbim::printSvg("not svg", 10, 10, &printer, &error));
    }
};

QTEST_MAIN(TestQolTools)
#include "test_qol_tools.moc"
