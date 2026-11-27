// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

#include <functional>

class QComboBox;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QTabWidget;
class QTableWidget;

namespace kimbim {

class Preferences;

// Versions > Git... (R4 follow-up): remotes, the NicGit token, fetch/push/pull, clone, and the design
// options (branches) on both sides. The engine does the work; this dialog only shows and calls it.
class GitDialog : public QDialog {
    Q_OBJECT
public:
    using Bridge = std::function<QJsonObject(const char*, const QStringList&)>;
    enum class Tab { Remote, Sync, Options, Clone };

    GitDialog(Bridge bridge, Preferences& prefs, bool versioned, QWidget* parent = nullptr);

    void setTab(Tab tab);
    QString cloneFolder() const { return m_cloneFolder; }
    QString switchTo() const { return m_switchTo; }
    bool needsReload() const { return m_needsReload; }
    bool changed() const { return m_changed; }

private:
    QWidget* buildRemoteTab();
    QWidget* buildSyncTab();
    QWidget* buildOptionsTab();
    QWidget* buildCloneTab();
    QJsonObject call(const char* fn, const QStringList& args = {});
    QJsonObject callBackground(const char* fn, const QStringList& args, const QString& label);
    void refresh();
    void refreshRemotes();
    void fillRemoteFields();
    void refreshSync();
    void refreshOptions();
    void refreshSyncStatus();
    void refreshTokenStatus();
    void addLog(const QString& text);
    static QString hostForUrl(const QString& url);
    static QString displayBranch(const QString& name);
    static QString shortId(const QString& id);

    Bridge m_bridge;
    Preferences& m_prefs;
    bool m_versioned;
    bool m_busy = false;
    QJsonObject m_state;
    QString m_cloneFolder;
    QString m_switchTo;
    bool m_needsReload = false;
    bool m_changed = false;

    QTabWidget* m_tabs = nullptr;
    // Remote tab
    QTableWidget* m_remoteTable = nullptr;
    QLineEdit* m_remoteName = nullptr;
    QLineEdit* m_remoteUrl = nullptr;
    QPushButton* m_remoteAdd = nullptr;
    QPushButton* m_remoteRemove = nullptr;
    QPushButton* m_remoteTest = nullptr;
    QLineEdit* m_gitUsername = nullptr;
    QLineEdit* m_gitToken = nullptr;
    QLabel* m_tokenStatus = nullptr;
    QPushButton* m_saveToken = nullptr;
    QPushButton* m_forgetToken = nullptr;
    QLineEdit* m_cloneUrl = nullptr;
    QLineEdit* m_cloneFolderEdit = nullptr;
    QLineEdit* m_cloneUser = nullptr;
    QLineEdit* m_cloneToken = nullptr;
    // Sync tab
    QComboBox* m_syncRemote = nullptr;
    QComboBox* m_syncBranch = nullptr;
    QLabel* m_syncStatus = nullptr;
    QLabel* m_syncDetail = nullptr;
    QPlainTextEdit* m_log = nullptr;
    // Options tab
    QTableWidget* m_optionsTable = nullptr;
    QLineEdit* m_newOption = nullptr;
    QTableWidget* m_remoteBranchesTable = nullptr;
};

} // namespace kimbim
