// SPDX-License-Identifier: GPL-3.0-or-later
#include <QApplication>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QComboBox>
#include <QCheckBox>
#include <QLabel>
#include <QLineEdit>
#include <QScrollArea>
#include <QScrollBar>
#include <QSpinBox>
#include <QtTest>

#include "Preferences.h"
#include "PreferencesDialog.h"

class TestPreferences : public QObject {
    Q_OBJECT
private slots:
    void defaultsWhenThereIsNoFile()
    {
        QTemporaryDir tmp;
        kimbim::Preferences p(tmp.filePath("preferences.json"));
        QVERIFY(p.load());
        QCOMPARE(p.language(), QString("auto"));
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.openIfc(), QString("make_nic"));
        QCOMPARE(p.autoVersion(), QString("off"));
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.largeIfcMb(), 5.0);
        QCOMPARE(p.trackerMode(), QString("always"));
        QCOMPARE(p.angleMode(), QString("absolute"));
        QCOMPARE(p.typedLengthUnit(), QString("metres"));
        QVERIFY(p.tabAnnotations());
        QVERIFY(p.templatesFolder().endsWith(QStringLiteral("NicBim Templates")));
        QVERIFY(p.recent().isEmpty());
    }

    void roundTripKeepsUnknownKeys()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("sub/preferences.json");
        {
            kimbim::Preferences p(path);
            p.setValue("new_views", "window");
            p.setValue("from_a_newer_kimbim", 42);
            p.setLayout(QByteArray("\x01\x02layout", 8));
            p.setWindowGeometry(QByteArray("\x03geometry", 9));
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        QCOMPARE(q.newViews(), QString("window"));
        QCOMPARE(q.value("from_a_newer_kimbim").toInt(), 42);
        QCOMPARE(q.layout(), QByteArray("\x01\x02layout", 8));
        QCOMPARE(q.windowGeometry(), QByteArray("\x03geometry", 9));
    }

    void aGarbledFileIsKeptAsideAndDefaultsUsed()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("{ not json");
        f.close();
        kimbim::Preferences p(path);
        QVERIFY(!p.load());
        QCOMPARE(p.newViews(), QString("tab"));
        QVERIFY(QFile::exists(path + ".bad"));
    }

    void recentFilesAreMostRecentFirstWithoutDuplicates()
    {
        kimbim::Preferences p;
        for (int i = 0; i < 12; ++i)
            p.addRecent(QStringLiteral("C:/p/%1.nic").arg(i));
        p.addRecent("C:/p/5.nic");
        const QStringList r = p.recent();
        QCOMPARE(r.size(), 10);
        QCOMPARE(r.first(), QString("C:/p/5.nic"));
        QCOMPARE(r.count("C:/p/5.nic"), 1);
        QVERIFY(!p.save()); // in memory only
    }

    void badValuesFallBackToDefaults()
    {
        kimbim::Preferences p;
        p.setValue("new_views", "sideways");
        p.setValue("recovery_minutes", -3);
        p.setValue("auto_version_every", "lots");
        p.setValue("large_ifc_mb", -1);
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.largeIfcMb(), 5.0);
        QCOMPARE(p.trackerMode(), QString("always"));
        QCOMPARE(p.angleMode(), QString("absolute"));
        QCOMPARE(p.typedLengthUnit(), QString("metres"));
        QVERIFY(p.tabAnnotations());
        QCOMPARE(p.scrollNavigation(), QString("auto")); // D89
        p.setValue("scroll_navigation", "sideways");
        QCOMPARE(p.scrollNavigation(), QString("auto"));
        QCOMPARE(p.fieldOfView(), 45.0); // D92
        p.setValue("field_of_view", 500);
        QCOMPARE(p.fieldOfView(), 45.0);
        QVERIFY(p.titleBarLevels() && p.titleBarCut() && p.titleBarVersions()); // D92
        p.setValue("title_bar_versions", false);
        QVERIFY(!p.titleBarVersions());
        QCOMPARE(p.selectSimilarScope(), QString("class_predefined")); // D92
        QCOMPARE(p.boxSelection(), QString("direction"));
        p.setValue("box_selection", "sideways");
        QCOMPARE(p.boxSelection(), QString("direction"));
        QVERIFY(p.splitJoin()); // D92
        p.setValue("split_join", false);
        QVERIFY(!p.splitJoin());
        QCOMPARE(p.theme(), QString("system"));
        p.setValue("theme", "sepia");
        QCOMPARE(p.theme(), QString("system"));
        QCOMPARE(p.gitPullDiverged(), QString("refuse"));
        p.setValue("git_pull_diverged", "rebase");
        QCOMPARE(p.gitPullDiverged(), QString("refuse"));
        QCOMPARE(p.updateChannel(), QString("off"));
        p.setValue("update_channel", "nightly");
        QCOMPARE(p.updateChannel(), QString("off"));
        QCOMPARE(p.gitRemoteName(), QString("origin"));
        p.setValue("git_remote_name", "  ");
        QCOMPARE(p.gitRemoteName(), QString("origin"));
        QCOMPARE(p.gitUsername(), QString("token"));
        p.setValue("git_username", "");
        QCOMPARE(p.gitUsername(), QString("token"));
        QCOMPARE(p.gitFetchMinutes(), 0);
        p.setValue("git_fetch_minutes", -2);
        QCOMPARE(p.gitFetchMinutes(), 0);
    }

    void theDialogWritesWhatTheUserPicked()
    {
        kimbim::Preferences p;
        kimbim::PreferencesDialog d(p, nullptr);
        QVERIFY(!d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("language")->setCurrentIndex(2); // auto, en, es
        QVERIFY(d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("newViews")->setCurrentIndex(1);
        d.findChild<QComboBox*>("openIfc")->setCurrentIndex(1);
        d.findChild<QComboBox*>("autoVersion")->setCurrentIndex(1);
        d.findChild<QSpinBox*>("autoVersionEvery")->setValue(3);
        d.findChild<QSpinBox*>("recoveryMinutes")->setValue(0);
        d.findChild<QSpinBox*>("largeIfcMb")->setValue(20);
        d.findChild<QComboBox*>("scrollNavigation")->setCurrentIndex(2); // auto, zoom, pan (D89)
        d.findChild<QSpinBox*>("fieldOfView")->setValue(60); // D92
        d.findChild<QCheckBox*>("titleBarVersions")->setChecked(false); // D92
        d.findChild<QCheckBox*>("titleBarLevels")->setChecked(false);
        d.findChild<QComboBox*>("selectSimilarScope")->setCurrentIndex(1); // class_predefined, type, class
        d.findChild<QComboBox*>("boxSelection")->setCurrentIndex(2); // direction, partial, entire
        d.findChild<QCheckBox*>("splitJoin")->setChecked(false);
        QVERIFY(!d.findChild<QComboBox*>("objectEditScope")); // D100: Edit... asks when it matters
        d.findChild<QCheckBox*>("keepRectangles")->setChecked(true);
        d.findChild<QComboBox*>("tracker")->setCurrentIndex(2); // always, typing, off
        d.findChild<QComboBox*>("angleMode")->setCurrentIndex(2); // absolute, relative, bearing
        d.findChild<QComboBox*>("typedLengthUnit")->setCurrentIndex(1); // metres, project
        d.findChild<QCheckBox*>("tabAnnotations")->setChecked(false);
        d.findChild<QCheckBox*>("panelsShrinkFirst")->setChecked(true);
        d.findChild<QLineEdit*>("authorName")->setText("Felipe");
        d.findChild<QLineEdit*>("templatesFolder")->setText("Z:/Plantillas");
        d.apply();
        QCOMPARE(p.language(), QString("es"));
        QCOMPARE(p.newViews(), QString("window"));
        QCOMPARE(p.openIfc(), QString("edit_ifc"));
        QCOMPARE(p.autoVersion(), QString("saves"));
        QCOMPARE(p.autoVersionEvery(), 3);
        QCOMPARE(p.recoveryMinutes(), 0);
        QCOMPARE(p.largeIfcMb(), 20.0);
        QCOMPARE(p.scrollNavigation(), QString("pan"));
        QCOMPARE(p.fieldOfView(), 60.0);
        QVERIFY(!p.titleBarLevels() && !p.titleBarVersions());
        QCOMPARE(p.selectSimilarScope(), QString("type"));
        QVERIFY(p.keepRectanglesRectangular());
        QCOMPARE(p.trackerMode(), QString("off"));
        QCOMPARE(p.angleMode(), QString("bearing"));
        QCOMPARE(p.typedLengthUnit(), QString("project"));
        QVERIFY(!p.tabAnnotations());
        QVERIFY(p.panelsShrinkFirst());
        QVERIFY(p.pinnedPanels().isEmpty());
        QCOMPARE(p.boxSelection(), QString("entire"));
        QVERIFY(!p.splitJoin());
        QCOMPARE(p.authorName(), QString("Felipe"));
        QCOMPARE(p.templatesFolder(), QString("Z:/Plantillas"));
    }

    void gitAndFolderPreferencesRoundTrip()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        {
            kimbim::Preferences p(path);
            p.setValue("theme", "dark");
            p.setValue("default_project_folder", "Z:/Projects");
            p.setValue("backup_folder", "Z:/Backups");
            p.setValue("cache_folder", "Z:/Cache");
            p.setValue("plugin_folder", "Z:/Plugins");
            p.setValue("git_server_url", "https://nicgit.example.com");
            p.setValue("git_remote_name", "nicgit");
            p.setValue("git_username", "ana");
            p.setValue("git_fetch_on_open", true);
            p.setValue("git_fetch_minutes", 15);
            p.setValue("git_push_after_save", true);
            p.setValue("git_pull_diverged", "merge");
            p.setValue("git_push_tags", false);
            p.setValue("http_proxy", "http://proxy:8080");
            p.setValue("update_channel", "beta");
            p.setValue("console_on_startup", true);
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        QCOMPARE(q.theme(), QString("dark"));
        QCOMPARE(q.defaultProjectFolder(), QString("Z:/Projects"));
        QCOMPARE(q.backupFolder(), QString("Z:/Backups"));
        QCOMPARE(q.cacheFolder(), QString("Z:/Cache"));
        QCOMPARE(q.pluginFolder(), QString("Z:/Plugins"));
        QCOMPARE(q.gitServerUrl(), QString("https://nicgit.example.com"));
        QCOMPARE(q.gitRemoteName(), QString("nicgit"));
        QCOMPARE(q.gitUsername(), QString("ana"));
        QVERIFY(q.gitFetchOnOpen());
        QCOMPARE(q.gitFetchMinutes(), 15);
        QVERIFY(q.gitPushAfterSave());
        QCOMPARE(q.gitPullDiverged(), QString("merge"));
        QVERIFY(!q.gitPushTags());
        QCOMPARE(q.httpProxy(), QString("http://proxy:8080"));
        QCOMPARE(q.updateChannel(), QString("beta"));
        QVERIFY(q.consoleOnStartup());
    }

    void gitSettingsInTheDialog()
    {
        kimbim::Preferences p;
        kimbim::PreferencesDialog d(p, nullptr);
        d.findChild<QComboBox*>("theme")->setCurrentIndex(2); // system, light, dark
        d.findChild<QLineEdit*>("defaultProjectFolder")->setText("Z:/Projects");
        d.findChild<QLineEdit*>("gitServerUrl")->setText("https://nicgit.example.com");
        d.findChild<QLineEdit*>("gitRemoteName")->setText("nicgit");
        d.findChild<QLineEdit*>("gitUsername")->setText("ana");
        d.findChild<QCheckBox*>("gitFetchOnOpen")->setChecked(true);
        d.findChild<QSpinBox*>("gitFetchMinutes")->setValue(20);
        d.findChild<QCheckBox*>("gitPushAfterSave")->setChecked(true);
        d.findChild<QComboBox*>("gitPullDiverged")->setCurrentIndex(1); // refuse, merge, remote, local
        d.findChild<QCheckBox*>("gitPushTags")->setChecked(false);
        d.findChild<QLineEdit*>("httpProxy")->setText("http://proxy:8080");
        d.findChild<QComboBox*>("updateChannel")->setCurrentIndex(2); // off, stable, beta
        d.findChild<QCheckBox*>("consoleOnStartup")->setChecked(true);
        d.apply();
        QCOMPARE(p.theme(), QString("dark"));
        QCOMPARE(p.defaultProjectFolder(), QString("Z:/Projects"));
        QCOMPARE(p.gitServerUrl(), QString("https://nicgit.example.com"));
        QCOMPARE(p.gitRemoteName(), QString("nicgit"));
        QCOMPARE(p.gitUsername(), QString("ana"));
        QVERIFY(p.gitFetchOnOpen());
        QCOMPARE(p.gitFetchMinutes(), 20);
        QVERIFY(p.gitPushAfterSave());
        QCOMPARE(p.gitPullDiverged(), QString("merge"));
        QVERIFY(!p.gitPushTags());
        QCOMPARE(p.httpProxy(), QString("http://proxy:8080"));
        QCOMPARE(p.updateChannel(), QString("beta"));
        QVERIFY(p.consoleOnStartup());
    }

    void workspacesRoundTrip()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        {
            kimbim::Preferences p(path);
            p.saveWorkspace("Wide plan", QByteArray("\x01layout one", 9));
            p.saveWorkspace("Section", QByteArray("\x02layout two", 9));
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        const QJsonObject all = q.workspaces();
        QCOMPARE(all.size(), 2);
        QCOMPARE(QByteArray::fromBase64(all.value("Wide plan").toString().toLatin1()),
                 QByteArray("\x01layout one", 9));
        q.deleteWorkspace("Section");
        QCOMPARE(q.workspaces().size(), 1);
        q.deleteWorkspace("Absent"); // harmless
        QCOMPARE(q.workspaces().size(), 1);
    }

    void toolbarVisibilityRoundTrip()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        {
            kimbim::Preferences p(path);
            QVERIFY(p.toolbarVisible("statusToolbar"));
            QVERIFY(!p.toolbarVisible("proposalToolbar", false));
            p.setToolbarVisible("statusToolbar", false);
            p.setToolbarVisible("proposalToolbar", true);
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        QVERIFY(!q.toolbarVisible("statusToolbar"));
        QVERIFY(q.toolbarVisible("proposalToolbar", false));
        QVERIFY(q.toolbarVisible("unknownToolbar"));
    }

    void preferencesScrollWhenTheWindowIsShort()
    {
        kimbim::Preferences p; // in memory
        kimbim::PreferencesDialog d(p, nullptr);
        d.resize(560, 420); // smaller than the form: the fields must stay reachable
        d.show();
        QApplication::processEvents();
        auto* scroll = d.findChild<QScrollArea*>(QStringLiteral("preferencesScroll"));
        QVERIFY(scroll && scroll->widgetResizable());
        QVERIFY(scroll->verticalScrollBar()->maximum() > 0);
    }
};

QTEST_MAIN(TestPreferences)
#include "test_preferences.moc"
