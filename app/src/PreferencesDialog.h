// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QScrollArea;
class QSpinBox;
class QStackedWidget;

namespace kimbim {

class Preferences;

// Edit > Preferences (D72): what this computer remembers, whatever project is open.
// The dialog is a category list on the left and one scrollable page on the right; the pages keep the
// widget object names the tests and the self-test use.
class PreferencesDialog : public QDialog {
    Q_OBJECT
public:
    PreferencesDialog(Preferences& prefs, QWidget* parent);
    void apply(); // writes every field to the preferences (OK calls it)
    void accept() override;

private:
    QWidget* generalPage();
    QWidget* filesPage();
    QWidget* drawingPage();
    QWidget* editingPage();
    QWidget* assistantPage();
    QWidget* gitPage();
    QWidget* networkPage();
    QWidget* pluginsPage();
    QWidget* updatesPage();
    QWidget* advancedPage();
    void addPage(const QString& title, QWidget* page);
    void refreshGitTokenStatus();
    bool validate();
    static QString hostForUrl(const QString& url);

    Preferences& m_prefs;
    QListWidget* m_sections;
    QStackedWidget* m_pages;
    QScrollArea* m_scroll;
    QComboBox* m_language;
    QLabel* m_restartNote;
    QComboBox* m_theme;
    QLineEdit* m_defaultProjectFolder;
    QLineEdit* m_templates;
    QLineEdit* m_officeLibrary;
    QLineEdit* m_backupFolder;
    QLineEdit* m_cacheFolder;
    QLineEdit* m_pluginFolder;
    QLineEdit* m_authorName;
    QLineEdit* m_authorEmail;
    QComboBox* m_newViews;
    QComboBox* m_openIfc;
    QComboBox* m_newSchema;
    QComboBox* m_autoVersion;
    QSpinBox* m_autoEvery;
    QSpinBox* m_recovery;
    QSpinBox* m_largeIfc;
    QSpinBox* m_drawingTimeout;
    QComboBox* m_drawingHlr;
    QComboBox* m_scrollMode; // D89
    QSpinBox* m_fieldOfView; // D92
    QCheckBox* m_northArrow; // D92: north indicator on plans
    QCheckBox* m_titleLevels; // D92: which controls the title bar holds
    QCheckBox* m_titleCut;
    QCheckBox* m_titleVersions;
    QComboBox* m_selectSimilar; // D92
    QComboBox* m_boxSelection;
    QCheckBox* m_splitJoin; // D92
    QComboBox* m_mergeProps; // D92
    QCheckBox* m_meshVertexSnaps; // D92
    QCheckBox* m_keepRectangles; // D92
    QComboBox* m_tracker; // D92: tracker and typed input
    QComboBox* m_angleMode;
    QComboBox* m_typedLength;
    QCheckBox* m_tabAnnotations;
    QCheckBox* m_panelsShrink;
    QSpinBox* m_underlayOpacity; // D92: new underlay defaults
    QCheckBox* m_underlayGrey;
    QLineEdit* m_underlayTint;
    QCheckBox* m_underlayLayerPerFile;
    // D102 phase 3: the Assistant's provider (the key itself lives in the OS credential store).
    QComboBox* m_assistantProvider;
    QLineEdit* m_assistantModel;
    QLineEdit* m_assistantBaseUrl;
    QLineEdit* m_assistantKey;
    QLabel* m_assistantKeyNote;
    // R4 follow-up: NicGit and other Git remotes.
    QLineEdit* m_gitServerUrl;
    QLineEdit* m_gitRemoteName;
    QLineEdit* m_gitUsername;
    QLineEdit* m_gitToken;
    QLabel* m_gitTokenStatus;
    QPushButton* m_gitForgetToken;
    QCheckBox* m_gitFetchOnOpen;
    QSpinBox* m_gitFetchMinutes;
    QCheckBox* m_gitPushAfterSave;
    QComboBox* m_gitPullDiverged;
    QCheckBox* m_gitPushTags;
    QLineEdit* m_httpProxy;
    QCheckBox* m_consoleOnStartup;
    QComboBox* m_updateChannel;
    QLabel* m_updateStatus;
};

} // namespace kimbim
