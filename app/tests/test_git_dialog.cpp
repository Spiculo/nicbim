// SPDX-License-Identifier: GPL-3.0-or-later
#include <QComboBox>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QTabWidget>
#include <QTableWidget>
#include <QtTest>

#include "GitDialog.h"
#include "Preferences.h"

class TestGitDialog : public QObject {
    Q_OBJECT
private slots:
    void buildsTheThreeTabsAndTheCloneTab()
    {
        kimbim::Preferences prefs;
        prefs.setValue("git_server_url", "https://nicgit.example.com");
        prefs.setValue("git_username", "ana");
        auto bridge = [](const char* fn, const QStringList&) {
            const QString name = QString::fromLatin1(fn);
            if (name == QLatin1String("git_state")) {
                return QJsonObject{
                    {"ok", true},
                    {"remotes", QJsonArray{QJsonObject{{"name", "origin"},
                                                       {"url", "https://nicgit.example.com/o/p.git"}}}},
                    {"default_remote", "origin"},
                    {"current", "main"},
                    {"head", "0123456789abcdef0123456789abcdef01234567"},
                    {"dirty", false},
                    {"unversioned", false},
                    {"status", QJsonObject{{"state", "up_to_date"}, {"head", "0123456789abcdef0123456789abcdef01234567"},
                                            {"ahead", 0}, {"behind", 0}}},
                    {"local_branches", QJsonArray{QJsonObject{{"name", "main"}, {"head", "0123456789abcdef0123456789abcdef01234567"},
                                                              {"author", "Ana"}, {"time", 1}, {"message", "Initial"}}}},
                    {"remote_branches", QJsonArray{QJsonObject{{"name", "main"}, {"head", "0123456789abcdef0123456789abcdef01234567"},
                                                                {"message", "Initial"}}}},
                };
            }
            if (name == QLatin1String("git_has_token"))
                return QJsonObject{{"ok", true}, {"stored", true}};
            if (name == QLatin1String("git_status"))
                return QJsonObject{{"ok", true}, {"state", "up_to_date"},
                                   {"head", "0123456789abcdef0123456789abcdef01234567"},
                                   {"ahead", 0}, {"behind", 0}};
            if (name == QLatin1String("remotes"))
                return QJsonObject{{"ok", true}, {"remotes", QJsonArray{}}};
            return QJsonObject{{"ok", true}};
        };
        kimbim::GitDialog dialog(bridge, prefs, true, nullptr);
        auto* tabs = dialog.findChild<QTabWidget*>(QStringLiteral("gitTabs"));
        QVERIFY(tabs);
        QCOMPARE(tabs->count(), 4);
        auto* remote = dialog.findChild<QTableWidget*>(QStringLiteral("remoteTable"));
        QVERIFY(remote);
        QCOMPARE(remote->rowCount(), 1);
        QCOMPARE(remote->item(0, 0)->text(), QString("origin"));
        auto* sync = dialog.findChild<QComboBox*>(QStringLiteral("syncRemote"));
        QVERIFY(sync);
        QCOMPARE(sync->count(), 1);
        auto* options = dialog.findChild<QTableWidget*>(QStringLiteral("optionsTable"));
        QVERIFY(options);
        QCOMPARE(options->rowCount(), 1);
        auto* token = dialog.findChild<QLabel*>(QStringLiteral("gitTokenStatus"));
        QVERIFY(token);
        QVERIFY(token->text().contains("nicgit.example.com"));
        dialog.setTab(kimbim::GitDialog::Tab::Options);
        QCOMPARE(tabs->currentIndex(), 2);
        dialog.setTab(kimbim::GitDialog::Tab::Clone);
        QCOMPARE(tabs->currentIndex(), 3);
        auto* url = dialog.findChild<QLineEdit*>(QStringLiteral("cloneUrl"));
        QVERIFY(url);
    }

    void cloneOnlyModeShowsOneTab()
    {
        kimbim::Preferences prefs;
        prefs.setValue("git_server_url", "https://nicgit.example.com");
        auto bridge = [](const char*, const QStringList&) { return QJsonObject{{"ok", true}}; };
        kimbim::GitDialog dialog(bridge, prefs, false, nullptr);
        auto* tabs = dialog.findChild<QTabWidget*>(QStringLiteral("gitTabs"));
        QVERIFY(tabs);
        QCOMPARE(tabs->count(), 1);
        auto* url = dialog.findChild<QLineEdit*>(QStringLiteral("cloneUrl"));
        QVERIFY(url);
        QCOMPARE(url->text(), QString("https://nicgit.example.com"));
        QVERIFY(dialog.findChild<QLineEdit*>(QStringLiteral("cloneFolder")));
    }
};

QTEST_MAIN(TestGitDialog)
#include "test_git_dialog.moc"
