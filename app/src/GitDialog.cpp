// SPDX-License-Identifier: GPL-3.0-or-later
#include "GitDialog.h"

#include <QApplication>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDir>
#include <QEventLoop>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QJsonArray>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QProgressDialog>
#include <QPushButton>
#include <QRegularExpression>
#include <QSignalBlocker>
#include <QTabWidget>
#include <QTableWidget>
#include <QThread>
#include <QUrl>
#include <QVBoxLayout>

#include "Preferences.h"

namespace kimbim {

namespace {
QLabel* hintLabel(const QString& text, QWidget* parent)
{
    auto* label = new QLabel(text, parent);
    label->setWordWrap(true);
    label->setTextFormat(Qt::PlainText);
    return label;
}

void setupTable(QTableWidget* table, const QStringList& headings)
{
    table->setColumnCount(int(headings.size()));
    table->setHorizontalHeaderLabels(headings);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    table->verticalHeader()->setVisible(false);
    table->horizontalHeader()->setStretchLastSection(true);
}

QTableWidgetItem* rowItem(const QString& text, const QString& data = QString())
{
    auto* item = new QTableWidgetItem(text);
    if (!data.isEmpty())
        item->setData(Qt::UserRole, data);
    return item;
}

QString selectedText(QTableWidget* table, int column = 0)
{
    const int row = table->currentRow();
    if (row < 0 || !table->item(row, column))
        return {};
    return table->item(row, column)->text();
}
} // namespace

GitDialog::GitDialog(Bridge bridge, Preferences& prefs, bool versioned, QWidget* parent)
    : QDialog(parent)
    , m_bridge(std::move(bridge))
    , m_prefs(prefs)
    , m_versioned(versioned)
{
    setObjectName(QStringLiteral("gitDialog"));
    setWindowTitle(m_versioned ? tr("Git") : tr("Clone project from remote"));
    resize(880, 660);
    setMinimumSize(700, 480);
    auto* layout = new QVBoxLayout(this);
    m_tabs = new QTabWidget(this);
    m_tabs->setObjectName(QStringLiteral("gitTabs"));
    layout->addWidget(m_tabs, 1);

    if (m_versioned) {
        m_tabs->addTab(buildRemoteTab(), tr("Remote"));
        m_tabs->addTab(buildSyncTab(), tr("Sync"));
        m_tabs->addTab(buildOptionsTab(), tr("Options"));
    }
    m_tabs->addTab(buildCloneTab(), tr("Clone"));

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    if (m_versioned)
        refresh();
    else {
        m_cloneUrl->setText(m_prefs.gitServerUrl());
        refreshTokenStatus();
    }
}

void GitDialog::setTab(Tab tab)
{
    if (!m_versioned) {
        m_tabs->setCurrentIndex(0);
        return;
    }
    const int index = tab == Tab::Remote ? 0 : tab == Tab::Sync ? 1 : tab == Tab::Options ? 2 : 3;
    m_tabs->setCurrentIndex(qBound(0, index, m_tabs->count() - 1));
}

QWidget* GitDialog::buildRemoteTab()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(hintLabel(tr("The server holds the project's Git repository. NicGit accepts a "
                                   "personal access token as the password; the token is kept in the "
                                   "operating system's credential store, never in the project."), page));
    m_remoteTable = new QTableWidget(page);
    m_remoteTable->setObjectName(QStringLiteral("remoteTable"));
    setupTable(m_remoteTable, {tr("Name"), tr("Address")});
    m_remoteTable->setMinimumHeight(110);
    layout->addWidget(m_remoteTable, 1);
    connect(m_remoteTable, &QTableWidget::itemSelectionChanged, this, [this] { fillRemoteFields(); });

    auto* buttons = new QHBoxLayout;
    m_remoteAdd = new QPushButton(tr("Add or update"), page);
    m_remoteAdd->setObjectName(QStringLiteral("remoteAddButton"));
    m_remoteRemove = new QPushButton(tr("Remove"), page);
    m_remoteRemove->setObjectName(QStringLiteral("remoteRemoveButton"));
    m_remoteTest = new QPushButton(tr("Test connection"), page);
    m_remoteTest->setObjectName(QStringLiteral("remoteTestButton"));
    buttons->addWidget(m_remoteAdd);
    buttons->addWidget(m_remoteRemove);
    buttons->addWidget(m_remoteTest);
    buttons->addStretch(1);
    layout->addLayout(buttons);

    auto* form = new QFormLayout;
    m_remoteName = new QLineEdit(m_prefs.gitRemoteName(), page);
    m_remoteName->setObjectName(QStringLiteral("remoteName"));
    m_remoteUrl = new QLineEdit(page);
    m_remoteUrl->setObjectName(QStringLiteral("remoteUrl"));
    m_remoteUrl->setPlaceholderText(QStringLiteral("https://nicgit.example.com/owner/project.git"));
    form->addRow(tr("Remote name:"), m_remoteName);
    form->addRow(tr("Address:"), m_remoteUrl);
    auto* serverRow = new QHBoxLayout;
    auto* useServer = new QPushButton(tr("Use the server from Preferences"), page);
    useServer->setObjectName(QStringLiteral("remoteDefaultButton"));
    serverRow->addWidget(useServer);
    serverRow->addStretch(1);
    form->addRow(QString(), serverRow);
    layout->addLayout(form);

    auto* tokenBox = new QGroupBox(tr("NicGit access token"), page);
    tokenBox->setObjectName(QStringLiteral("gitTokenBox"));
    auto* tokenForm = new QFormLayout(tokenBox);
    m_gitUsername = new QLineEdit(m_prefs.gitUsername(), tokenBox);
    m_gitUsername->setObjectName(QStringLiteral("gitUsername"));
    m_gitUsername->setToolTip(tr("NicGit accepts any user name with a valid token as the password"));
    m_gitToken = new QLineEdit(tokenBox);
    m_gitToken->setObjectName(QStringLiteral("gitToken"));
    m_gitToken->setEchoMode(QLineEdit::Password);
    m_gitToken->setPlaceholderText(tr("Paste a token from NicGit: Settings > Access"));
    m_tokenStatus = new QLabel(tokenBox);
    m_tokenStatus->setObjectName(QStringLiteral("gitTokenStatus"));
    m_tokenStatus->setWordWrap(true);
    auto* tokenButtons = new QHBoxLayout;
    m_saveToken = new QPushButton(tr("Save token"), tokenBox);
    m_saveToken->setObjectName(QStringLiteral("gitSaveToken"));
    m_forgetToken = new QPushButton(tr("Forget token"), tokenBox);
    m_forgetToken->setObjectName(QStringLiteral("gitForgetToken"));
    tokenButtons->addWidget(m_saveToken);
    tokenButtons->addWidget(m_forgetToken);
    tokenButtons->addStretch(1);
    tokenForm->addRow(tr("User name:"), m_gitUsername);
    tokenForm->addRow(tr("Token:"), m_gitToken);
    tokenForm->addRow(QString(), m_tokenStatus);
    tokenForm->addRow(QString(), tokenButtons);
    layout->addWidget(tokenBox);
    layout->addStretch(1);

    connect(m_gitToken, &QLineEdit::textChanged, this, [this] {
        if (!m_gitToken->text().trimmed().isEmpty()) {
            m_tokenStatus->setText(tr("This token is used for the next operation; press Save token to keep it."));
            if (m_saveToken)
                m_saveToken->setEnabled(true);
            if (m_forgetToken)
                m_forgetToken->setEnabled(false);
        } else {
            refreshTokenStatus();
        }
    });
    connect(m_remoteUrl, &QLineEdit::textChanged, this, [this] { refreshTokenStatus(); });
    connect(useServer, &QPushButton::clicked, this, [this] {
        if (!m_prefs.gitServerUrl().isEmpty())
            m_remoteUrl->setText(m_prefs.gitServerUrl());
    });
    connect(m_remoteAdd, &QPushButton::clicked, this, [this] {
        const QString name = m_remoteName->text().trimmed();
        const QString url = m_remoteUrl->text().trimmed();
        if (name.isEmpty() || url.isEmpty()) {
            QMessageBox::information(this, tr("Remote"), tr("Give the remote a name and an address."));
            return;
        }
        const QJsonObject r = call("git_set_remote", {name, url});
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("Remote"), r.value("error").toString());
            return;
        }
        m_changed = true;
        addLog(tr("Remote %1 saved").arg(name));
        refresh();
    });
    connect(m_remoteRemove, &QPushButton::clicked, this, [this] {
        const QString name = selectedText(m_remoteTable);
        if (name.isEmpty())
            return;
        if (QMessageBox::question(this, tr("Remove remote"),
                tr("Remove the remote %1 from this project? The server keeps its copy.").arg(name))
            != QMessageBox::Yes)
            return;
        const QJsonObject r = call("remove_remote", {name});
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("Remote"), r.value("error").toString());
            return;
        }
        m_changed = true;
        addLog(tr("Remote %1 removed").arg(name));
        refresh();
    });
    connect(m_remoteTest, &QPushButton::clicked, this, [this] {
        const QString url = m_remoteUrl->text().trimmed();
        if (url.isEmpty())
            return;
        const QJsonObject r = callBackground("git_test_remote",
            {url, m_gitUsername->text().trimmed(), m_gitToken->text().trimmed()},
            tr("Testing the connection..."));
        if (!r.value("ok").toBool()) {
            addLog(tr("Connection failed: %1").arg(r.value("error").toString()));
            QMessageBox::warning(this, tr("Test connection"), r.value("error").toString());
            return;
        }
        addLog(tr("Connected to %1: %n option(s)", nullptr, int(r.value("count").toInt()))
                   .arg(hostForUrl(url)));
    });
    connect(m_saveToken, &QPushButton::clicked, this, [this] {
        const QString token = m_gitToken->text().trimmed();
        const QString host = hostForUrl(m_remoteUrl->text().trimmed().isEmpty()
                                            ? m_prefs.gitServerUrl()
                                            : m_remoteUrl->text().trimmed());
        if (host.isEmpty() || token.isEmpty())
            return;
        const QJsonObject r = call("git_set_token", {host, token});
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("Token"), r.value("error").toString());
            return;
        }
        m_gitToken->clear();
        m_changed = true;
        addLog(tr("Token stored for %1").arg(host));
        refreshTokenStatus();
    });
    connect(m_forgetToken, &QPushButton::clicked, this, [this] {
        const QString host = hostForUrl(m_remoteUrl->text().trimmed().isEmpty()
                                            ? m_prefs.gitServerUrl()
                                            : m_remoteUrl->text().trimmed());
        if (host.isEmpty())
            return;
        const QJsonObject r = call("git_clear_token", {host});
        if (r.value("ok").toBool()) {
            m_changed = true;
            addLog(tr("Token removed for %1").arg(host));
            refreshTokenStatus();
        }
    });

    return page;
}

QWidget* GitDialog::buildSyncTab()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    auto* top = new QHBoxLayout;
    m_syncRemote = new QComboBox(page);
    m_syncRemote->setObjectName(QStringLiteral("syncRemote"));
    m_syncBranch = new QComboBox(page);
    m_syncBranch->setObjectName(QStringLiteral("syncBranch"));
    top->addWidget(new QLabel(tr("Remote:"), page));
    top->addWidget(m_syncRemote, 1);
    top->addWidget(new QLabel(tr("Option:"), page));
    top->addWidget(m_syncBranch, 1);
    layout->addLayout(top);

    m_syncStatus = new QLabel(page);
    m_syncStatus->setObjectName(QStringLiteral("syncStatus"));
    m_syncStatus->setWordWrap(true);
    m_syncDetail = new QLabel(page);
    m_syncDetail->setObjectName(QStringLiteral("syncDetail"));
    m_syncDetail->setWordWrap(true);
    layout->addWidget(m_syncStatus);
    layout->addWidget(m_syncDetail);

    auto* actions = new QHBoxLayout;
    auto* fetch = new QPushButton(tr("Fetch"), page);
    fetch->setObjectName(QStringLiteral("fetchButton"));
    auto* pull = new QPushButton(tr("Pull"), page);
    pull->setObjectName(QStringLiteral("pullButton"));
    auto* push = new QPushButton(tr("Push"), page);
    push->setObjectName(QStringLiteral("pushButton"));
    auto* pushTags = new QPushButton(tr("Push tags"), page);
    pushTags->setObjectName(QStringLiteral("pushTagsButton"));
    auto* force = new QPushButton(tr("Force push"), page);
    force->setObjectName(QStringLiteral("forcePushButton"));
    auto* remove = new QPushButton(tr("Delete remote option"), page);
    remove->setObjectName(QStringLiteral("deleteRemoteBranchButton"));
    actions->addWidget(fetch);
    actions->addWidget(pull);
    actions->addWidget(push);
    actions->addWidget(pushTags);
    actions->addWidget(force);
    actions->addWidget(remove);
    actions->addStretch(1);
    layout->addLayout(actions);

    m_log = new QPlainTextEdit(page);
    m_log->setObjectName(QStringLiteral("gitLog"));
    m_log->setReadOnly(true);
    m_log->setMinimumHeight(120);
    layout->addWidget(m_log, 1);

    connect(m_syncRemote, &QComboBox::currentIndexChanged, this, [this] { refreshSyncStatus(); });
    connect(m_syncBranch, &QComboBox::currentIndexChanged, this, [this] { refreshSyncStatus(); });
    connect(fetch, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        if (remote.isEmpty())
            return;
        const QJsonObject r = callBackground("git_fetch", {remote}, tr("Fetching from the remote..."));
        if (!r.value("ok").toBool()) {
            addLog(tr("Fetch failed: %1").arg(r.value("error").toString()));
            return;
        }
        m_changed = true;
        addLog(tr("Fetched %1 (%n option(s))", nullptr, int(r.value("branches").toArray().size())).arg(remote));
        refresh();
    });
    connect(pull, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        const QString branch = m_syncBranch->currentData().toString();
        const QString branchName = m_syncBranch->currentText();
        if (remote.isEmpty() || branch.isEmpty())
            return;
        QString mode = m_prefs.gitPullDiverged();
        QJsonObject r = callBackground("pull", {remote, branch, QString(), QString(), mode},
            tr("Pulling from the remote..."));
        if (!r.value("ok").toBool()
            && r.value("error").toString().contains(QLatin1String("diverged"))) {
            QMessageBox box(this);
            box.setWindowTitle(tr("Pull"));
            box.setText(tr("This option and the remote have both changed. How should they be brought together?"));
            box.setInformativeText(tr("A record merge uses NicBim's object merge, never Git's text merge."));
            QPushButton* merge = box.addButton(tr("Merge with NicBim"), QMessageBox::AcceptRole);
            QPushButton* theirs = box.addButton(tr("Use the remote"), QMessageBox::DestructiveRole);
            QPushButton* ours = box.addButton(tr("Use this option"), QMessageBox::DestructiveRole);
            box.addButton(QMessageBox::Cancel);
            box.exec();
            if (box.clickedButton() == merge)
                mode = QStringLiteral("merge");
            else if (box.clickedButton() == theirs)
                mode = QStringLiteral("force_remote");
            else if (box.clickedButton() == ours)
                mode = QStringLiteral("force_local");
            else
                return;
            r = callBackground("pull", {remote, branch, QString(), QString(), mode},
                tr("Pulling from the remote..."));
        }
        if (!r.value("ok").toBool()) {
            const QString error = r.value("error").toString();
            addLog(tr("Pull failed: %1").arg(error));
            if (error.contains(QLatin1String("conflict")))
                QMessageBox::information(this, tr("Pull"),
                    tr("%1\n\nOpen Versions > Combine options to choose what to keep in each conflict, then pull again.")
                        .arg(error));
            else
                QMessageBox::warning(this, tr("Pull"), error);
            return;
        }
        m_changed = true;
        const QString status = r.value("status").toString();
        if (status != QLatin1String("up_to_date"))
            m_needsReload = true;
        addLog(tr("Pull: %1 (%2)").arg(status, branchName));
        refresh();
    });
    connect(push, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        const QString branch = m_syncBranch->currentData().toString();
        if (remote.isEmpty() || branch.isEmpty())
            return;
        const QJsonObject r = callBackground("push",
            {remote, branch, QStringLiteral("false"), m_prefs.gitPushTags() ? QStringLiteral("true") : QStringLiteral("false")},
            tr("Pushing to the remote..."));
        if (!r.value("ok").toBool()) {
            addLog(tr("Push failed: %1").arg(r.value("error").toString()));
            QMessageBox::warning(this, tr("Push"), r.value("error").toString());
            return;
        }
        addLog(tr("Pushed %1 to %2").arg(branch, remote));
        refresh();
    });
    connect(pushTags, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        if (remote.isEmpty())
            return;
        const QJsonObject r = callBackground("git_push_tags", {remote}, tr("Pushing milestones..."));
        addLog(r.value("ok").toBool() ? tr("Milestones pushed to %1").arg(remote)
                                      : tr("Push tags failed: %1").arg(r.value("error").toString()));
        refresh();
    });
    connect(force, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        const QString branch = m_syncBranch->currentData().toString();
        if (remote.isEmpty() || branch.isEmpty())
            return;
        if (QMessageBox::warning(this, tr("Force push"),
                tr("Replace the remote option %1 with this one?\n\nOnly commits this project already "
                   "knows are replaced: a commit somebody else pushed since the last fetch is kept.").arg(branch),
                QMessageBox::Cancel | QMessageBox::Yes, QMessageBox::Cancel) != QMessageBox::Yes)
            return;
        const QJsonObject r = callBackground("push",
            {remote, branch, QStringLiteral("true"), m_prefs.gitPushTags() ? QStringLiteral("true") : QStringLiteral("false")},
            tr("Pushing to the remote..."));
        addLog(r.value("ok").toBool() ? tr("Force-pushed %1 to %2").arg(branch, remote)
                                      : tr("Force push failed: %1").arg(r.value("error").toString()));
        refresh();
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        const QString remote = m_syncRemote->currentData().toString();
        const QString branch = m_syncBranch->currentData().toString();
        const QString branchName = m_syncBranch->currentText();
        if (remote.isEmpty() || branch.isEmpty())
            return;
        if (QMessageBox::warning(this, tr("Delete remote option"),
                tr("Delete the option %1 from %2? Its history on the server is removed.").arg(branchName, remote),
                QMessageBox::Cancel | QMessageBox::Yes, QMessageBox::Cancel) != QMessageBox::Yes)
            return;
        const QJsonObject r = callBackground("delete_remote_branch", {remote, branch},
            tr("Deleting the remote option..."));
        addLog(r.value("ok").toBool() ? tr("Deleted %1 from %2").arg(branchName, remote)
                                      : tr("Delete failed: %1").arg(r.value("error").toString()));
        refresh();
    });
    return page;
}

QWidget* GitDialog::buildOptionsTab()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(new QLabel(tr("Design options on this computer"), page));
    m_optionsTable = new QTableWidget(page);
    m_optionsTable->setObjectName(QStringLiteral("optionsTable"));
    setupTable(m_optionsTable, {tr("Option"), tr("Latest version"), tr("Author"), tr("Message")});
    m_optionsTable->setMinimumHeight(140);
    layout->addWidget(m_optionsTable, 1);

    auto* localButtons = new QHBoxLayout;
    auto* newName = new QLineEdit(page);
    newName->setObjectName(QStringLiteral("newOptionName"));
    newName->setPlaceholderText(tr("New option name"));
    m_newOption = newName;
    auto* create = new QPushButton(tr("Create option"), page);
    create->setObjectName(QStringLiteral("createOptionButton"));
    auto* switchButton = new QPushButton(tr("Switch to option"), page);
    switchButton->setObjectName(QStringLiteral("switchOptionButton"));
    auto* deleteButton = new QPushButton(tr("Delete option"), page);
    deleteButton->setObjectName(QStringLiteral("deleteOptionButton"));
    localButtons->addWidget(newName, 1);
    localButtons->addWidget(create);
    localButtons->addWidget(switchButton);
    localButtons->addWidget(deleteButton);
    layout->addLayout(localButtons);

    layout->addWidget(new QLabel(tr("Options on the remote (fetch first)"), page));
    m_remoteBranchesTable = new QTableWidget(page);
    m_remoteBranchesTable->setObjectName(QStringLiteral("remoteBranchesTable"));
    setupTable(m_remoteBranchesTable, {tr("Option"), tr("Latest version"), tr("Message")});
    m_remoteBranchesTable->setMinimumHeight(120);
    layout->addWidget(m_remoteBranchesTable, 1);
    auto* remoteButtons = new QHBoxLayout;
    auto* checkout = new QPushButton(tr("Create option from the selected remote option"), page);
    checkout->setObjectName(QStringLiteral("checkoutRemoteButton"));
    auto* removeRemote = new QPushButton(tr("Delete the selected remote option"), page);
    removeRemote->setObjectName(QStringLiteral("deleteRemoteOptionButton"));
    remoteButtons->addWidget(checkout);
    remoteButtons->addWidget(removeRemote);
    remoteButtons->addStretch(1);
    layout->addLayout(remoteButtons);

    connect(create, &QPushButton::clicked, this, [this] {
        const QString name = m_newOption->text().trimmed();
        if (name.isEmpty())
            return;
        const QJsonObject r = call("create_option", {name});
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("New option"), r.value("error").toString());
            return;
        }
        m_changed = true;
        m_newOption->clear();
        addLog(tr("Option %1 created").arg(name));
        refresh();
    });
    connect(switchButton, &QPushButton::clicked, this, [this] {
        const QString name = selectedText(m_optionsTable);
        if (name.isEmpty())
            return;
        m_switchTo = name;
        accept();
    });
    connect(deleteButton, &QPushButton::clicked, this, [this] {
        const QString name = selectedText(m_optionsTable);
        if (name.isEmpty())
            return;
        if (QMessageBox::question(this, tr("Delete option"),
                tr("Delete the design option %1 and its versions from this project?").arg(name))
            != QMessageBox::Yes)
            return;
        const QJsonObject r = call("delete_option", {name});
        if (r.value("ok").toBool())
            m_changed = true;
        addLog(r.value("ok").toBool() ? tr("Option %1 deleted").arg(name)
                                      : tr("Delete failed: %1").arg(r.value("error").toString()));
        refresh();
    });
    connect(checkout, &QPushButton::clicked, this, [this] {
        const int row = m_remoteBranchesTable->currentRow();
        if (row < 0 || !m_remoteBranchesTable->item(row, 0))
            return;
        const QString encoded = m_remoteBranchesTable->item(row, 0)->data(Qt::UserRole).toString();
        const QString suggested = displayBranch(encoded);
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("Create option from the remote"),
            tr("Name the new option:"), QLineEdit::Normal, suggested, &ok);
        if (!ok || name.trimmed().isEmpty())
            return;
        const QString remote = m_syncRemote->currentData().toString();
        const QJsonObject r = call("create_option_from",
            {name.trimmed(), QStringLiteral("refs/remotes/%1/%2").arg(remote, encoded)});
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("Create option from the remote"), r.value("error").toString());
            return;
        }
        m_changed = true;
        m_needsReload = true;
        addLog(tr("Option %1 created from %2").arg(name.trimmed(), displayBranch(encoded)));
        refresh();
    });
    connect(removeRemote, &QPushButton::clicked, this, [this] {
        const int row = m_remoteBranchesTable->currentRow();
        if (row < 0 || !m_remoteBranchesTable->item(row, 0))
            return;
        const QString encoded = m_remoteBranchesTable->item(row, 0)->data(Qt::UserRole).toString();
        const QString remote = m_syncRemote->currentData().toString();
        if (QMessageBox::warning(this, tr("Delete remote option"),
                tr("Delete the option %1 from %2?").arg(displayBranch(encoded), remote),
                QMessageBox::Cancel | QMessageBox::Yes, QMessageBox::Cancel) != QMessageBox::Yes)
            return;
        const QJsonObject r = callBackground("delete_remote_branch", {remote, encoded},
            tr("Deleting the remote option..."));
        if (r.value("ok").toBool())
            m_changed = true;
        addLog(r.value("ok").toBool() ? tr("Deleted %1 from %2").arg(displayBranch(encoded), remote)
                                      : tr("Delete failed: %1").arg(r.value("error").toString()));
        refresh();
    });
    return page;
}

QWidget* GitDialog::buildCloneTab()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(hintLabel(m_versioned
            ? tr("Clone a NicGit project into a new folder. The folder becomes a project you can open "
                 "and edit; its history comes from the server.")
            : tr("Clone a NicBim project from NicGit into a new folder. Paste the project address from "
                 "the NicGit project page, and create a personal access token in NicGit under "
                 "Settings > Access."), page));
    auto* form = new QFormLayout;
    m_cloneUrl = new QLineEdit(page);
    m_cloneUrl->setObjectName(QStringLiteral("cloneUrl"));
    m_cloneUrl->setPlaceholderText(QStringLiteral("https://nicgit.example.com/owner/project.git"));
    form->addRow(tr("Project address:"), m_cloneUrl);
    auto* folderRow = new QHBoxLayout;
    m_cloneFolderEdit = new QLineEdit(page);
    m_cloneFolderEdit->setObjectName(QStringLiteral("cloneFolder"));
    auto* browse = new QPushButton(tr("Browse..."), page);
    connect(browse, &QPushButton::clicked, this, [this] {
        const QString folder = QFileDialog::getExistingDirectory(this, tr("Choose a new folder"),
            m_prefs.defaultProjectFolder());
        if (!folder.isEmpty())
            m_cloneFolderEdit->setText(folder);
    });
    folderRow->addWidget(m_cloneFolderEdit, 1);
    folderRow->addWidget(browse);
    form->addRow(tr("New folder:"), folderRow);
    m_cloneUser = new QLineEdit(m_prefs.gitUsername(), page);
    m_cloneUser->setObjectName(QStringLiteral("cloneUsername"));
    m_cloneToken = new QLineEdit(page);
    m_cloneToken->setObjectName(QStringLiteral("cloneToken"));
    m_cloneToken->setEchoMode(QLineEdit::Password);
    m_cloneToken->setPlaceholderText(tr("A token, or leave empty to use the stored one"));
    form->addRow(tr("User name:"), m_cloneUser);
    form->addRow(tr("Token:"), m_cloneToken);
    layout->addLayout(form);
    auto* cloneButton = new QPushButton(tr("Clone project"), page);
    cloneButton->setObjectName(QStringLiteral("cloneButton"));
    layout->addWidget(cloneButton, 0, Qt::AlignLeft);
    layout->addStretch(1);
    connect(cloneButton, &QPushButton::clicked, this, [this] {
        const QString url = m_cloneUrl->text().trimmed();
        const QString folder = m_cloneFolderEdit->text().trimmed();
        if (url.isEmpty() || folder.isEmpty()) {
            QMessageBox::information(this, tr("Clone project"), tr("Choose the project address and a new folder."));
            return;
        }
        const QJsonObject r = callBackground("git_clone",
            {url, folder, m_cloneUser->text().trimmed(), m_cloneToken->text().trimmed()},
            tr("Cloning the project..."));
        if (!r.value("ok").toBool()) {
            addLog(tr("Clone failed: %1").arg(r.value("error").toString()));
            QMessageBox::warning(this, tr("Clone project"), r.value("error").toString());
            return;
        }
        m_cloneFolder = r.value("folder").toString();
        m_changed = true;
        addLog(tr("Cloned %1 (option %2)").arg(m_cloneFolder, displayBranch(r.value("branch").toString())));
        accept();
    });
    return page;
}

QJsonObject GitDialog::call(const char* fn, const QStringList& args)
{
    QJsonObject r = m_bridge(fn, args);
    if (r.isEmpty())
        r = QJsonObject{{"ok", false}, {"error", tr("The engine returned no answer")}};
    return r;
}

QJsonObject GitDialog::callBackground(const char* fn, const QStringList& args, const QString& label)
{
    if (m_busy)
        return QJsonObject{{"ok", false}, {"error", tr("Another Git operation is running")}};
    m_busy = true;
    m_tabs->setEnabled(false);
    QJsonObject result;
    QThread* worker = QThread::create([&] { result = m_bridge(fn, args); });
    QProgressDialog progress(label, QString(), 0, 0, this);
    progress.setWindowTitle(tr("Git"));
    progress.setWindowModality(Qt::ApplicationModal);
    progress.setCancelButton(nullptr);
    progress.setMinimumDuration(300);
    QEventLoop loop;
    connect(worker, &QThread::finished, &loop, &QEventLoop::quit);
    QApplication::setOverrideCursor(Qt::WaitCursor);
    worker->start();
    loop.exec(QEventLoop::ExcludeUserInputEvents);
    worker->wait();
    delete worker;
    QApplication::restoreOverrideCursor();
    m_tabs->setEnabled(true);
    m_busy = false;
    if (result.isEmpty())
        result = QJsonObject{{"ok", false}, {"error", tr("The engine returned no answer")}};
    return result;
}

void GitDialog::refresh()
{
    if (!m_versioned)
        return;
    m_state = call("git_state");
    if (!m_state.value("ok").toBool()) {
        addLog(tr("Could not read the project's Git state: %1").arg(m_state.value("error").toString()));
        return;
    }
    refreshRemotes();
    refreshSync();
    refreshOptions();
    refreshTokenStatus();
}

void GitDialog::refreshRemotes()
{
    const QString keep = selectedText(m_remoteTable);
    const QJsonArray remotes = m_state.value("remotes").toArray();
    {
        QSignalBlocker block(m_remoteTable);
        m_remoteTable->setRowCount(int(remotes.size()));
        int select = -1;
        for (int i = 0; i < remotes.size(); ++i) {
            const QJsonObject remote = remotes[i].toObject();
            m_remoteTable->setItem(i, 0, rowItem(remote.value("name").toString()));
            m_remoteTable->setItem(i, 1, rowItem(remote.value("url").toString()));
            if (!keep.isEmpty() && remote.value("name").toString() == keep)
                select = i;
        }
        if (select >= 0)
            m_remoteTable->selectRow(select);
        else if (remotes.size() > 0)
            m_remoteTable->selectRow(0);
    }
    if (remotes.isEmpty()) {
        m_remoteTable->clearSelection();
        if (m_remoteName->text().trimmed().isEmpty())
            m_remoteName->setText(m_prefs.gitRemoteName());
        if (m_remoteUrl->text().trimmed().isEmpty())
            m_remoteUrl->setText(m_prefs.gitServerUrl());
        if (m_cloneUrl && m_cloneUrl->text().trimmed().isEmpty())
            m_cloneUrl->setText(m_prefs.gitServerUrl());
    }
    fillRemoteFields();
}

void GitDialog::fillRemoteFields()
{
    const int row = m_remoteTable->currentRow();
    if (row >= 0 && m_remoteTable->item(row, 0)) {
        const QString url = m_remoteTable->item(row, 1) ? m_remoteTable->item(row, 1)->text() : QString();
        m_remoteName->setText(m_remoteTable->item(row, 0)->text());
        m_remoteUrl->setText(url);
        if (m_cloneUrl && m_cloneUrl->text().trimmed().isEmpty())
            m_cloneUrl->setText(url);
    }
    refreshTokenStatus();
}

void GitDialog::refreshSync()
{
    const QString remote = m_syncRemote->currentData().toString();
    const QString branch = m_syncBranch->currentData().toString();
    {
        QSignalBlocker block(m_syncRemote);
        m_syncRemote->clear();
        for (const auto& value : m_state.value("remotes").toArray()) {
            const QJsonObject item = value.toObject();
            m_syncRemote->addItem(item.value("name").toString(), item.value("name").toString());
        }
        if (!remote.isEmpty())
            m_syncRemote->setCurrentIndex(qMax(0, m_syncRemote->findData(remote)));
    }
    {
        QSignalBlocker block(m_syncBranch);
        m_syncBranch->clear();
        for (const auto& value : m_state.value("local_branches").toArray()) {
            const QJsonObject item = value.toObject();
            m_syncBranch->addItem(displayBranch(item.value("name").toString()), item.value("name").toString());
        }
        if (!branch.isEmpty()) {
            const int index = m_syncBranch->findData(branch);
            if (index >= 0)
                m_syncBranch->setCurrentIndex(index);
        }
    }
    refreshSyncStatus();
}

void GitDialog::refreshSyncStatus()
{
    const QString remote = m_syncRemote->currentData().toString();
    const QString branchRef = m_syncBranch->currentData().toString();
    const QString branch = m_syncBranch->currentText();
    if (remote.isEmpty() || branchRef.isEmpty()) {
        m_syncStatus->setText(tr("No remote or option yet."));
        m_syncDetail->clear();
        return;
    }
    const QJsonObject r = call("git_status", {remote, branchRef});
    if (!r.value("ok").toBool()) {
        m_syncStatus->setText(tr("Status unavailable: %1").arg(r.value("error").toString()));
        m_syncDetail->clear();
        return;
    }
    const QString state = r.value("state").toString();
    const int ahead = r.value("ahead").toInt();
    const int behind = r.value("behind").toInt();
    if (state == QLatin1String("no_remote"))
        m_syncStatus->setText(tr("No remote configured."));
    else if (state == QLatin1String("up_to_date"))
        m_syncStatus->setText(tr("Up to date with %1/%2.").arg(remote, branch));
    else if (state == QLatin1String("ahead"))
        m_syncStatus->setText(tr("%n version(s) to push to %1/%2.", nullptr, ahead).arg(remote, branch));
    else if (state == QLatin1String("behind"))
        m_syncStatus->setText(tr("%n version(s) to pull from %1/%2.", nullptr, behind).arg(remote, branch));
    else if (state == QLatin1String("diverged"))
        m_syncStatus->setText(tr("Diverged: %1 to push and %2 to pull.").arg(ahead).arg(behind));
    else
        m_syncStatus->setText(state);
    QString detail = tr("Option %1 · latest %2").arg(branch, shortId(r.value("head").toString()));
    if (m_state.value("unversioned").toBool())
        detail += tr(" · unsaved changes");
    else if (m_state.value("dirty").toBool())
        detail += tr(" · the model has changes");
    if (!r.value("remote_head").toString().isEmpty())
        detail += tr(" · remote %1").arg(shortId(r.value("remote_head").toString()));
    m_syncDetail->setText(detail);
}

void GitDialog::refreshOptions()
{
    const QString keepOption = selectedText(m_optionsTable);
    const QJsonArray options = m_state.value("local_branches").toArray();
    {
        QSignalBlocker block(m_optionsTable);
        m_optionsTable->setRowCount(int(options.size()));
        int select = -1;
        for (int i = 0; i < options.size(); ++i) {
            const QJsonObject item = options[i].toObject();
            const QString name = displayBranch(item.value("name").toString());
            m_optionsTable->setItem(i, 0, rowItem(name, item.value("name").toString()));
            m_optionsTable->setItem(i, 1, rowItem(shortId(item.value("head").toString())));
            m_optionsTable->setItem(i, 2, rowItem(item.value("author").toString()));
            m_optionsTable->setItem(i, 3, rowItem(item.value("message").toString()));
            if (!keepOption.isEmpty() && name == keepOption)
                select = i;
        }
        if (select >= 0)
            m_optionsTable->selectRow(select);
        else if (options.size() > 0)
            m_optionsTable->selectRow(0);
    }

    const QJsonArray remote = m_state.value("remote_branches").toArray();
    {
        QSignalBlocker block(m_remoteBranchesTable);
        m_remoteBranchesTable->setRowCount(int(remote.size()));
        for (int i = 0; i < remote.size(); ++i) {
            const QJsonObject item = remote[i].toObject();
            const QString encoded = item.value("name").toString();
            m_remoteBranchesTable->setItem(i, 0, rowItem(displayBranch(encoded), encoded));
            m_remoteBranchesTable->setItem(i, 1, rowItem(shortId(item.value("head").toString())));
            m_remoteBranchesTable->setItem(i, 2, rowItem(item.value("message").toString()));
        }
        if (remote.size() > 0)
            m_remoteBranchesTable->selectRow(0);
    }
}

void GitDialog::refreshTokenStatus()
{
    if (!m_tokenStatus || !m_gitToken)
        return;
    QString url = m_remoteUrl ? m_remoteUrl->text().trimmed() : QString();
    if (url.isEmpty() && m_cloneUrl)
        url = m_cloneUrl->text().trimmed();
    if (url.isEmpty())
        url = m_prefs.gitServerUrl();
    const QString host = hostForUrl(url);
    if (host.isEmpty()) {
        m_tokenStatus->setText(tr("The token is stored per server. Add the project address first."));
        if (m_forgetToken)
            m_forgetToken->setEnabled(false);
        if (m_saveToken)
            m_saveToken->setEnabled(!m_gitToken->text().trimmed().isEmpty());
        return;
    }
    const QJsonObject r = call("git_has_token", {host});
    const bool stored = r.value("stored").toBool();
    m_tokenStatus->setText(stored ? tr("A token is stored for %1.").arg(host)
                                  : tr("No token stored for %1 yet.").arg(host));
    if (m_forgetToken)
        m_forgetToken->setEnabled(stored);
    if (m_saveToken)
        m_saveToken->setEnabled(!m_gitToken->text().trimmed().isEmpty());
}

void GitDialog::addLog(const QString& text)
{
    if (m_log)
        m_log->appendPlainText(text);
}

QString GitDialog::hostForUrl(const QString& url)
{
    const QString text = url.trimmed();
    if (text.isEmpty())
        return {};
    const QUrl parsed(text);
    if (parsed.isValid() && !parsed.scheme().isEmpty()) {
        const QString scheme = parsed.scheme().toLower();
        if (scheme == QLatin1String("http") || scheme == QLatin1String("https")
            || scheme == QLatin1String("ssh") || scheme == QLatin1String("git")) {
            const QString host = parsed.host().toLower();
            const int port = parsed.port();
            const bool standard = (scheme == QLatin1String("http") && port == 80)
                || (scheme == QLatin1String("https") && port == 443);
            return port > 0 && !standard ? QStringLiteral("%1:%2").arg(host).arg(port) : host;
        }
        return {};
    }
    static const QRegularExpression scp(QStringLiteral("^[^@]+@([^:]+):"));
    const auto match = scp.match(text);
    return match.hasMatch() ? match.captured(1).toLower() : QString();
}

QString GitDialog::displayBranch(const QString& name)
{
    return QUrl::fromPercentEncoding(name.toUtf8());
}

QString GitDialog::shortId(const QString& id)
{
    return id.left(8);
}

} // namespace kimbim
