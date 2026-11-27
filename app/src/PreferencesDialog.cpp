// SPDX-License-Identifier: GPL-3.0-or-later
#include "PreferencesDialog.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QFrame>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QStackedWidget>
#include <QStandardPaths>
#include <QUrl>
#include <QVBoxLayout>

#include "Preferences.h"
#include "PythonEngine.h"

namespace kimbim {

namespace {
QComboBox* choice(QWidget* parent, const char* name, const QList<QPair<QString, QString>>& items,
                  const QString& current)
{
    auto* box = new QComboBox(parent);
    box->setObjectName(QLatin1String(name));
    for (const auto& [label, value] : items)
        box->addItem(label, value);
    box->setCurrentIndex(qMax(0, box->findData(current)));
    return box;
}

QLabel* title(const QString& text, QWidget* parent)
{
    auto* label = new QLabel(QStringLiteral("<b>%1</b>").arg(text), parent);
    label->setTextFormat(Qt::RichText);
    return label;
}

QLabel* note(const QString& text, QWidget* parent)
{
    auto* label = new QLabel(text, parent);
    label->setWordWrap(true);
    label->setTextFormat(Qt::PlainText);
    return label;
}

QHBoxLayout* folderRow(QLineEdit* field, QWidget* parent, const QString& caption)
{
    auto* row = new QHBoxLayout;
    auto* browse = new QPushButton(QObject::tr("Browse..."), parent);
    QObject::connect(browse, &QPushButton::clicked, parent, [field, parent, caption] {
        const QString folder = QFileDialog::getExistingDirectory(parent, caption, field->text());
        if (!folder.isEmpty())
            field->setText(folder);
    });
    row->addWidget(field, 1);
    row->addWidget(browse);
    return row;
}

QLineEdit* pathEdit(const QString& value, const char* name, QWidget* parent)
{
    auto* edit = new QLineEdit(value, parent);
    edit->setObjectName(QLatin1String(name));
    return edit;
}
} // namespace

PreferencesDialog::PreferencesDialog(Preferences& prefs, QWidget* parent)
    : QDialog(parent)
    , m_prefs(prefs)
    , m_sections(new QListWidget(this))
    , m_pages(new QStackedWidget(this))
    , m_scroll(new QScrollArea(this))
{
    setWindowTitle(tr("Preferences"));
    resize(900, 720);
    setMinimumSize(680, 460);
    auto* layout = new QVBoxLayout(this);
    auto* body = new QHBoxLayout;
    m_sections->setObjectName(QStringLiteral("preferencesSections"));
    m_sections->setFixedWidth(180);
    m_sections->setFrameShape(QFrame::NoFrame);
    m_scroll->setObjectName(QStringLiteral("preferencesScroll"));
    m_scroll->setWidgetResizable(true);
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_pages->setObjectName(QStringLiteral("preferencesPages"));
    m_scroll->setWidget(m_pages);
    body->addWidget(m_sections);
    body->addWidget(m_scroll, 1);
    layout->addLayout(body, 1);

    addPage(tr("General"), generalPage());
    addPage(tr("Files and folders"), filesPage());
    addPage(tr("Drawing"), drawingPage());
    addPage(tr("Editing and navigation"), editingPage());
    addPage(tr("Assistant"), assistantPage());
    addPage(tr("Git and sync"), gitPage());
    addPage(tr("Network"), networkPage());
    addPage(tr("Plugins and scripting"), pluginsPage());
    addPage(tr("Updates"), updatesPage());
    addPage(tr("Advanced"), advancedPage());
    m_sections->setCurrentRow(0);
    connect(m_sections, &QListWidget::currentRowChanged, this,
        [this](int row) { m_pages->setCurrentIndex(qMax(0, row)); });

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
    refreshGitTokenStatus();
}

void PreferencesDialog::addPage(const QString& label, QWidget* page)
{
    m_sections->addItem(label);
    m_pages->addWidget(page);
}

QWidget* PreferencesDialog::generalPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("General"), page));
    auto* form = new QFormLayout;
    m_language = choice(page, "language", {{tr("Automatic (system)"), "auto"}, {QStringLiteral("English"), "en"},
                                              {QStringLiteral("Español"), "es"}}, m_prefs.language());
    form->addRow(tr("Language:"), m_language);
    m_restartNote = new QLabel(tr("The language changes the next time NicBim starts."), page);
    m_restartNote->setObjectName(QStringLiteral("restartNote"));
    m_restartNote->setVisible(false);
    form->addRow(QString(), m_restartNote);
    connect(m_language, &QComboBox::currentIndexChanged, this,
        [this] { m_restartNote->setVisible(m_language->currentData().toString() != m_prefs.language()); });
    m_authorName = new QLineEdit(m_prefs.authorName(), page);
    m_authorName->setObjectName(QStringLiteral("authorName"));
    m_authorName->setPlaceholderText(tr("Shown on versions and to others opening your files"));
    form->addRow(tr("Your name:"), m_authorName);
    m_authorEmail = new QLineEdit(m_prefs.authorEmail(), page);
    m_authorEmail->setObjectName(QStringLiteral("authorEmail"));
    form->addRow(tr("Your email:"), m_authorEmail);
    m_theme = choice(page, "theme", {{tr("Follow the system"), "system"}, {tr("Light"), "light"},
                                        {tr("Dark"), "dark"}}, m_prefs.theme());
    form->addRow(tr("Appearance:"), m_theme);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::filesPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Files and folders"), page));
    auto* form = new QFormLayout;
    m_defaultProjectFolder = pathEdit(m_prefs.defaultProjectFolder(), "defaultProjectFolder", page);
    form->addRow(tr("Default project folder:"), folderRow(m_defaultProjectFolder, page, tr("Default project folder")));
    m_templates = new QLineEdit(m_prefs.templatesFolder(), page);
    m_templates->setObjectName(QStringLiteral("templatesFolder"));
    form->addRow(tr("Templates folder:"), folderRow(m_templates, page, tr("Templates folder")));
    m_officeLibrary = new QLineEdit(m_prefs.value(QStringLiteral("office_library")).toString(), page);
    m_officeLibrary->setObjectName(QStringLiteral("officeLibrary"));
    m_officeLibrary->setPlaceholderText(tr("A shared folder of object files (.nicobj) and IFC type libraries (.ifc)"));
    form->addRow(tr("Office library:"), folderRow(m_officeLibrary, page, tr("Office library")));
    m_backupFolder = pathEdit(m_prefs.backupFolder(), "backupFolder", page);
    m_backupFolder->setPlaceholderText(tr("Empty: the app data folder"));
    form->addRow(tr("Recovery copies:"), folderRow(m_backupFolder, page, tr("Recovery copies")));
    m_cacheFolder = pathEdit(m_prefs.cacheFolder(), "cacheFolder", page);
    m_cacheFolder->setPlaceholderText(tr("Empty: the app data folder"));
    form->addRow(tr("Temporary and cache files:"), folderRow(m_cacheFolder, page, tr("Temporary files")));
    m_openIfc = choice(page, "openIfc", {{tr("Make a .nic beside it"), "make_nic"}, {tr("Edit the IFC directly"), "edit_ifc"}},
        m_prefs.openIfc());
    form->addRow(tr("Opening an IFC file:"), m_openIfc);
    m_newSchema = choice(page, "newProjectSchema", {{tr("IFC4 (widest support)"), "IFC4"},
        {tr("IFC4X3 (current ISO standard)"), "IFC4X3"}}, m_prefs.newProjectSchema());
    m_newSchema->setToolTip(tr("The IFC schema of new projects. An office template keeps its own schema; "
                               "File › Change IFC schema converts an open model."));
    form->addRow(tr("New projects use:"), m_newSchema);
    m_largeIfc = new QSpinBox(page);
    m_largeIfc->setObjectName(QStringLiteral("largeIfcMb"));
    m_largeIfc->setRange(0, 10000);
    m_largeIfc->setSuffix(tr(" MB"));
    m_largeIfc->setSpecialValueText(tr("Never"));
    m_largeIfc->setValue(qRound(m_prefs.largeIfcMb()));
    m_largeIfc->setToolTip(tr("Making a .nic from a large IFC can take minutes; above this size NicBim asks first"));
    form->addRow(tr("Ask before converting IFC files over:"), m_largeIfc);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::drawingPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Drawing"), page));
    auto* form = new QFormLayout;
    m_drawingTimeout = new QSpinBox(page);
    m_drawingTimeout->setObjectName(QStringLiteral("drawingTimeout"));
    m_drawingTimeout->setRange(0, 3600);
    m_drawingTimeout->setSuffix(tr(" s"));
    m_drawingTimeout->setSpecialValueText(tr("No limit"));
    m_drawingTimeout->setValue(m_prefs.drawingTimeout());
    m_drawingTimeout->setToolTip(tr("Give up on a drawing that takes longer: the hidden-line pass can be slow on a large model"));
    form->addRow(tr("Drawing generation timeout:"), m_drawingTimeout);
    m_drawingHlr = choice(page, "drawingHlr", {{tr("Exact (faster on detailed models)"), "exact"},
                                                  {tr("Polygon (faster on curved models)"), "poly"}}, m_prefs.drawingHlr());
    m_drawingHlr->setToolTip(tr("The serializer's hidden-line mode: try the other one if drawings are slow"));
    form->addRow(tr("Hidden-line mode:"), m_drawingHlr);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::editingPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Editing and navigation"), page));
    auto* form = new QFormLayout;
    m_newViews = choice(page, "newViews", {{tr("Tabs"), "tab"}, {tr("Free windows"), "window"}}, m_prefs.newViews());
    form->addRow(tr("New views open as:"), m_newViews);
    m_scrollMode = choice(page, "scrollNavigation", {{tr("Automatic (touchpad scroll pans, mouse wheel zooms)"), "auto"},
        {tr("Mouse: the wheel zooms"), "zoom"}, {tr("Mac trackpad: two fingers pan"), "pan"},
        {tr("Precision touchpad: two fingers pan, finely"), "precision"}}, m_prefs.scrollNavigation());
    m_scrollMode->setToolTip(tr("Two-finger scroll with Shift orbits the 3D view"));
    form->addRow(tr("Scroll and touchpad:"), m_scrollMode);
    m_tracker = choice(page, "tracker", {{tr("Always while drawing"), "always"}, {tr("While typing"), "typing"},
                                         {tr("Off"), "off"}}, m_prefs.trackerMode());
    m_tracker->setToolTip(tr("The tracker beside the cursor: always, only once something is typed, or not at all"));
    form->addRow(tr("Tracker:"), m_tracker);
    m_angleMode = choice(page, "angleMode", {{tr("Absolute (from east)"), "absolute"},
                                             {tr("Relative to the previous segment"), "relative"},
                                             {tr("Bearing (clockwise from north)"), "bearing"}}, m_prefs.angleMode());
    m_angleMode->setToolTip(tr("How typed and live angles are measured"));
    form->addRow(tr("Angle input:"), m_angleMode);
    m_typedLength = choice(page, "typedLengthUnit", {{tr("Metres"), "metres"}, {tr("Project unit"), "project"}},
        m_prefs.typedLengthUnit());
    m_typedLength->setToolTip(tr("The unit of lengths typed into the tracker and the length field"));
    form->addRow(tr("Typed lengths in:"), m_typedLength);
    m_tabAnnotations = new QCheckBox(tr("Tab also cycles through annotations and 2D drafting"), page);
    m_tabAnnotations->setObjectName(QStringLiteral("tabAnnotations"));
    m_tabAnnotations->setChecked(m_prefs.tabAnnotations());
    form->addRow(QString(), m_tabAnnotations);
    m_panelsShrink = new QCheckBox(tr("Shrink the panels first on small screens"), page);
    m_panelsShrink->setObjectName(QStringLiteral("panelsShrinkFirst"));
    m_panelsShrink->setChecked(m_prefs.panelsShrinkFirst());
    form->addRow(QString(), m_panelsShrink);
    m_fieldOfView = new QSpinBox(page);
    m_fieldOfView->setObjectName(QStringLiteral("fieldOfView"));
    m_fieldOfView->setRange(5, 120);
    m_fieldOfView->setSuffix(tr("°"));
    m_fieldOfView->setValue(qRound(m_prefs.fieldOfView()));
    m_fieldOfView->setToolTip(tr("How wide the perspective view sees: 45° is a normal lens"));
    form->addRow(tr("Perspective field of view:"), m_fieldOfView);
    m_northArrow = new QCheckBox(tr("Show a north arrow on plans (once true north is set)"), page);
    m_northArrow->setObjectName(QStringLiteral("northArrow"));
    m_northArrow->setChecked(m_prefs.northArrowPlans());
    form->addRow(QString(), m_northArrow);
    auto* chromeRow = new QHBoxLayout;
    m_titleLevels = new QCheckBox(tr("Levels"), page);
    m_titleLevels->setObjectName(QStringLiteral("titleBarLevels"));
    m_titleLevels->setChecked(m_prefs.titleBarLevels());
    m_titleCut = new QCheckBox(tr("Plan cut"), page);
    m_titleCut->setObjectName(QStringLiteral("titleBarCut"));
    m_titleCut->setChecked(m_prefs.titleBarCut());
    m_titleVersions = new QCheckBox(tr("Versions"), page);
    m_titleVersions->setObjectName(QStringLiteral("titleBarVersions"));
    m_titleVersions->setChecked(m_prefs.titleBarVersions());
    chromeRow->addWidget(m_titleLevels);
    chromeRow->addWidget(m_titleCut);
    chromeRow->addWidget(m_titleVersions);
    chromeRow->addStretch(1);
    form->addRow(tr("Title bar shows:"), chromeRow);
    m_selectSimilar = choice(page, "selectSimilarScope", {{tr("Same class and predefined type"), "class_predefined"},
        {tr("Same type object"), "type"}, {tr("Same class"), "class"}}, m_prefs.selectSimilarScope());
    m_selectSimilar->setToolTip(tr("What Select similar takes: elements sharing the selected element's class and predefined type, its type object, or its class"));
    form->addRow(tr("Select similar by:"), m_selectSimilar);
    m_boxSelection = choice(page, "boxSelection", {{tr("Drag direction (left window, right crossing)"), "direction"},
        {tr("Any touched element (partial)"), "partial"}, {tr("Only fully enclosed elements (entire)"), "entire"}},
        m_prefs.boxSelection());
    m_boxSelection->setToolTip(tr("How a box selects elements"));
    form->addRow(tr("Box selection:"), m_boxSelection);
    m_splitJoin = new QCheckBox(tr("Join split and trimmed pieces (hold Ctrl to leave them apart)"), page);
    m_splitJoin->setObjectName(QStringLiteral("splitJoin"));
    m_splitJoin->setChecked(m_prefs.splitJoin());
    form->addRow(QString(), m_splitJoin);
    m_mergeProps = choice(page, "mergeProps", {{tr("Keep the first element's properties"), "keep"},
        {tr("Refuse when their properties differ"), "refuse"}}, m_prefs.mergeProps());
    m_mergeProps->setToolTip(tr("Merging two collinear walls (Join): the result keeps the first wall's properties, or the merge is refused if they differ"));
    form->addRow(tr("Merging elements:"), m_mergeProps);
    m_meshVertexSnaps = new QCheckBox(tr("Snap to element mesh vertices while drawing"), page);
    m_meshVertexSnaps->setObjectName(QStringLiteral("meshVertexSnaps"));
    m_meshVertexSnaps->setChecked(m_prefs.meshVertexSnaps());
    m_meshVertexSnaps->setToolTip(tr("Adds the corners of slabs, roofs and other elements to the snap points"));
    form->addRow(QString(), m_meshVertexSnaps);
    m_keepRectangles = new QCheckBox(tr("Keep rectangles rectangular when a corner is dragged"), page);
    m_keepRectangles->setObjectName(QStringLiteral("keepRectangles"));
    m_keepRectangles->setChecked(m_prefs.keepRectanglesRectangular());
    m_keepRectangles->setToolTip(tr("On: the two sides next to the dragged corner follow it; off: the corner moves freely"));
    form->addRow(QString(), m_keepRectangles);
    m_underlayOpacity = new QSpinBox(page);
    m_underlayOpacity->setObjectName(QStringLiteral("underlayOpacity"));
    m_underlayOpacity->setRange(5, 100);
    m_underlayOpacity->setSuffix(tr(" %"));
    m_underlayOpacity->setValue(qRound(m_prefs.underlayOpacity() * 100));
    form->addRow(tr("New underlay opacity:"), m_underlayOpacity);
    m_underlayGrey = new QCheckBox(tr("Show new underlays in grey"), page);
    m_underlayGrey->setObjectName(QStringLiteral("underlayGrey"));
    m_underlayGrey->setChecked(m_prefs.underlayGreyscale());
    form->addRow(QString(), m_underlayGrey);
    m_underlayTint = new QLineEdit(m_prefs.underlayTint(), page);
    m_underlayTint->setObjectName(QStringLiteral("underlayTint"));
    m_underlayTint->setPlaceholderText(QStringLiteral("#rrggbb"));
    m_underlayTint->setToolTip(tr("Tint new underlays this colour (leave empty for none)"));
    form->addRow(tr("New underlay tint:"), m_underlayTint);
    m_underlayLayerPerFile = new QCheckBox(tr("Put each new underlay on its own layer, named after the file"), page);
    m_underlayLayerPerFile->setObjectName(QStringLiteral("underlayLayerPerFile"));
    m_underlayLayerPerFile->setChecked(m_prefs.underlayLayerPerFile());
    form->addRow(QString(), m_underlayLayerPerFile);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::assistantPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Assistant"), page));
    layout->addWidget(note(tr("The Assistant panel uses your own provider and key. Keys are stored in the "
                              "operating system's credential store, never in preferences.json."), page));
    auto* form = new QFormLayout;
    m_assistantProvider = choice(page, "assistantProvider",
                                 {{QStringLiteral("Anthropic"), "anthropic"}, {tr("OpenAI-compatible"), "openai"}},
                                 m_prefs.value(QStringLiteral("assistant_provider")).toString());
    form->addRow(tr("Provider:"), m_assistantProvider);
    m_assistantModel = new QLineEdit(m_prefs.value(QStringLiteral("assistant_model")).toString(), page);
    m_assistantModel->setObjectName(QStringLiteral("assistantModel"));
    m_assistantModel->setPlaceholderText(tr("Model name"));
    form->addRow(tr("Model:"), m_assistantModel);
    m_assistantBaseUrl = new QLineEdit(m_prefs.value(QStringLiteral("assistant_base_url")).toString(), page);
    m_assistantBaseUrl->setObjectName(QStringLiteral("assistantBaseUrl"));
    m_assistantBaseUrl->setPlaceholderText(tr("Default endpoint when empty (OpenAI-compatible: base URL ending in /v1)"));
    form->addRow(tr("Base URL:"), m_assistantBaseUrl);
    m_assistantKey = new QLineEdit(page);
    m_assistantKey->setObjectName(QStringLiteral("assistantKey"));
    m_assistantKey->setEchoMode(QLineEdit::Password);
    m_assistantKey->setPlaceholderText(tr("Leave empty to keep the stored key"));
    form->addRow(tr("API key:"), m_assistantKey);
    m_assistantKeyNote = note(tr("Keys are stored in the operating system's credential store."), page);
    m_assistantKeyNote->setObjectName(QStringLiteral("assistantKeyNote"));
    form->addRow(QString(), m_assistantKeyNote);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::gitPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Git and sync"), page));
    layout->addWidget(note(tr("NicGit is the forge for NicBim projects. The project address looks like "
                              "https://<server>/<owner>/<project>.git. The token is stored in the operating "
                              "system's credential store, one per server; it is never written to the project."), page));
    auto* form = new QFormLayout;
    m_gitServerUrl = new QLineEdit(m_prefs.gitServerUrl(), page);
    m_gitServerUrl->setObjectName(QStringLiteral("gitServerUrl"));
    m_gitServerUrl->setPlaceholderText(tr("https://nicgit.example.com (or your self-hosted server)"));
    form->addRow(tr("Default server:"), m_gitServerUrl);
    m_gitRemoteName = new QLineEdit(m_prefs.gitRemoteName(), page);
    m_gitRemoteName->setObjectName(QStringLiteral("gitRemoteName"));
    form->addRow(tr("Default remote name:"), m_gitRemoteName);
    m_gitUsername = new QLineEdit(m_prefs.gitUsername(), page);
    m_gitUsername->setObjectName(QStringLiteral("gitUsername"));
    m_gitUsername->setToolTip(tr("NicGit accepts any user name with a valid token as the password"));
    form->addRow(tr("NicGit user name:"), m_gitUsername);
    m_gitToken = new QLineEdit(page);
    m_gitToken->setObjectName(QStringLiteral("gitToken"));
    m_gitToken->setEchoMode(QLineEdit::Password);
    m_gitToken->setPlaceholderText(tr("Leave empty to keep the stored token"));
    form->addRow(tr("Access token:"), m_gitToken);
    m_gitTokenStatus = new QLabel(page);
    m_gitTokenStatus->setObjectName(QStringLiteral("gitTokenStatus"));
    m_gitTokenStatus->setWordWrap(true);
    auto* tokenRow = new QHBoxLayout;
    m_gitForgetToken = new QPushButton(tr("Forget the stored token"), page);
    m_gitForgetToken->setObjectName(QStringLiteral("gitForgetToken"));
    tokenRow->addWidget(m_gitForgetToken);
    tokenRow->addStretch(1);
    form->addRow(QString(), m_gitTokenStatus);
    form->addRow(QString(), tokenRow);
    m_gitFetchOnOpen = new QCheckBox(tr("Fetch when a project opens"), page);
    m_gitFetchOnOpen->setObjectName(QStringLiteral("gitFetchOnOpen"));
    m_gitFetchOnOpen->setChecked(m_prefs.gitFetchOnOpen());
    form->addRow(QString(), m_gitFetchOnOpen);
    m_gitFetchMinutes = new QSpinBox(page);
    m_gitFetchMinutes->setObjectName(QStringLiteral("gitFetchMinutes"));
    m_gitFetchMinutes->setRange(0, 1440);
    m_gitFetchMinutes->setSuffix(tr(" min"));
    m_gitFetchMinutes->setSpecialValueText(tr("Off"));
    m_gitFetchMinutes->setValue(m_prefs.gitFetchMinutes());
    form->addRow(tr("Fetch every:"), m_gitFetchMinutes);
    m_gitPushAfterSave = new QCheckBox(tr("Push the current option after Save version"), page);
    m_gitPushAfterSave->setObjectName(QStringLiteral("gitPushAfterSave"));
    m_gitPushAfterSave->setChecked(m_prefs.gitPushAfterSave());
    form->addRow(QString(), m_gitPushAfterSave);
    m_gitPullDiverged = choice(page, "gitPullDiverged",
        {{tr("Refuse and explain (safer)"), "refuse"}, {tr("Merge with NicBim's record merge"), "merge"},
         {tr("Use the remote option"), "force_remote"}, {tr("Use this option (force push)"), "force_local"}},
        m_prefs.gitPullDiverged());
    m_gitPullDiverged->setToolTip(tr("What Pull offers when this option and the remote both changed"));
    form->addRow(tr("When an option and the remote diverged:"), m_gitPullDiverged);
    m_gitPushTags = new QCheckBox(tr("Push milestones (tags) with the branch"), page);
    m_gitPushTags->setObjectName(QStringLiteral("gitPushTags"));
    m_gitPushTags->setChecked(m_prefs.gitPushTags());
    form->addRow(QString(), m_gitPushTags);
    layout->addLayout(form);
    layout->addStretch(1);

    connect(m_gitServerUrl, &QLineEdit::textChanged, this, [this] { refreshGitTokenStatus(); });
    connect(m_gitToken, &QLineEdit::textChanged, this, [this] {
        if (!m_gitToken->text().trimmed().isEmpty()) {
            const QString host = hostForUrl(m_gitServerUrl->text());
            m_gitTokenStatus->setText(tr("A new token for %1 is saved when you press OK.")
                .arg(host.isEmpty() ? tr("the server") : host));
            if (m_gitForgetToken)
                m_gitForgetToken->setEnabled(false);
        } else {
            refreshGitTokenStatus();
        }
    });
    connect(m_gitForgetToken, &QPushButton::clicked, this, [this] {
        const QString host = hostForUrl(m_gitServerUrl->text());
        if (host.isEmpty())
            return;
        const QJsonObject r = PythonEngine::instance().callJson("git_clear_token", {host}).object();
        if (r.value("ok").toBool())
            refreshGitTokenStatus();
    });
    return page;
}

QWidget* PreferencesDialog::networkPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Network"), page));
    layout->addWidget(note(tr("Used by Git and by the Assistant. Leave empty to use the system proxy. "
                              "Git and Python read these settings the next time they connect."), page));
    auto* form = new QFormLayout;
    m_httpProxy = new QLineEdit(m_prefs.httpProxy(), page);
    m_httpProxy->setObjectName(QStringLiteral("httpProxy"));
    m_httpProxy->setPlaceholderText(QStringLiteral("http://proxy.example.com:8080"));
    form->addRow(tr("HTTP proxy:"), m_httpProxy);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::pluginsPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Plugins and scripting"), page));
    layout->addWidget(note(tr("Plugins are Python files in the plugins folder. They run when NicBim starts "
                              "and when Help > Plugins > Reload is pressed."), page));
    auto* form = new QFormLayout;
    m_pluginFolder = pathEdit(m_prefs.pluginFolder(), "pluginFolder", page);
    m_pluginFolder->setPlaceholderText(tr("Empty: the app data folder"));
    form->addRow(tr("Plugins folder:"), folderRow(m_pluginFolder, page, tr("Plugins folder")));
    m_consoleOnStartup = new QCheckBox(tr("Open the Python console at startup"), page);
    m_consoleOnStartup->setObjectName(QStringLiteral("consoleOnStartup"));
    m_consoleOnStartup->setChecked(m_prefs.consoleOnStartup());
    form->addRow(QString(), m_consoleOnStartup);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::updatesPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Updates"), page));
    layout->addWidget(note(tr("The update check reads the public GitHub releases page. It sends nothing "
                              "about you or your projects."), page));
    auto* form = new QFormLayout;
    m_updateChannel = choice(page, "updateChannel", {{tr("Do not check"), "off"}, {tr("Stable releases"), "stable"},
                                                        {tr("Beta releases"), "beta"}}, m_prefs.updateChannel());
    form->addRow(tr("Check for updates:"), m_updateChannel);
    layout->addLayout(form);
    m_updateStatus = new QLabel(page);
    m_updateStatus->setObjectName(QStringLiteral("updateStatus"));
    m_updateStatus->setWordWrap(true);
    auto* check = new QPushButton(tr("Check now"), page);
    check->setObjectName(QStringLiteral("updateCheckButton"));
    auto* row = new QHBoxLayout;
    row->addWidget(check);
    row->addWidget(m_updateStatus, 1);
    layout->addLayout(row);
    connect(check, &QPushButton::clicked, this, [this] {
        if (!PythonEngine::instance().isRunning()) {
            m_updateStatus->setText(tr("Start NicBim normally to check for updates."));
            return;
        }
        const QJsonObject r = PythonEngine::instance().callJson("check_for_updates",
            {QStringLiteral(KIMBIM_VERSION), m_updateChannel->currentData().toString()}).object();
        if (!r.value("ok").toBool()) {
            m_updateStatus->setText(r.value("error").toString());
            return;
        }
        if (r.value("update").toBool())
            m_updateStatus->setText(tr("Version %1 is available (you have %2): %3")
                .arg(r.value("latest").toString(), r.value("current").toString(), r.value("url").toString()));
        else
            m_updateStatus->setText(tr("NicBim %1 is up to date.").arg(r.value("current").toString()));
    });
    layout->addStretch(1);
    return page;
}

QWidget* PreferencesDialog::advancedPage()
{
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->addWidget(title(tr("Advanced"), page));
    auto* form = new QFormLayout;
    auto* autoRow = new QHBoxLayout;
    m_autoVersion = choice(page, "autoVersion", {{tr("Off"), "off"}, {tr("Every N saves"), "saves"},
                                                    {tr("Every N minutes"), "minutes"}}, m_prefs.autoVersion());
    m_autoEvery = new QSpinBox(page);
    m_autoEvery->setObjectName(QStringLiteral("autoVersionEvery"));
    m_autoEvery->setRange(1, 999);
    m_autoEvery->setValue(m_prefs.autoVersionEvery());
    m_autoEvery->setEnabled(m_prefs.autoVersion() != QLatin1String("off"));
    connect(m_autoVersion, &QComboBox::currentIndexChanged, this,
        [this] { m_autoEvery->setEnabled(m_autoVersion->currentData().toString() != QLatin1String("off")); });
    autoRow->addWidget(m_autoVersion, 1);
    autoRow->addWidget(new QLabel(tr("N ="), page));
    autoRow->addWidget(m_autoEvery);
    form->addRow(tr("Automatic versions:"), autoRow);
    m_recovery = new QSpinBox(page);
    m_recovery->setObjectName(QStringLiteral("recoveryMinutes"));
    m_recovery->setRange(0, 120);
    m_recovery->setSuffix(tr(" min"));
    m_recovery->setSpecialValueText(tr("Off"));
    m_recovery->setValue(m_prefs.recoveryMinutes());
    form->addRow(tr("Recovery copy every:"), m_recovery);
    layout->addLayout(form);
    layout->addStretch(1);
    return page;
}

void PreferencesDialog::apply()
{
    m_prefs.setValue(QStringLiteral("language"), m_language->currentData().toString());
    m_prefs.setValue(QStringLiteral("theme"), m_theme->currentData().toString());
    m_prefs.setValue(QStringLiteral("default_project_folder"), m_defaultProjectFolder->text().trimmed());
    m_prefs.setValue(QStringLiteral("templates_folder"), m_templates->text().trimmed());
    m_prefs.setValue(QStringLiteral("office_library"), m_officeLibrary->text().trimmed());
    m_prefs.setValue(QStringLiteral("backup_folder"), m_backupFolder->text().trimmed());
    m_prefs.setValue(QStringLiteral("cache_folder"), m_cacheFolder->text().trimmed());
    m_prefs.setValue(QStringLiteral("plugin_folder"), m_pluginFolder->text().trimmed());
    m_prefs.setValue(QStringLiteral("author_name"), m_authorName->text().trimmed());
    m_prefs.setValue(QStringLiteral("author_email"), m_authorEmail->text().trimmed());
    m_prefs.setValue(QStringLiteral("new_views"), m_newViews->currentData().toString());
    m_prefs.setValue(QStringLiteral("open_ifc"), m_openIfc->currentData().toString());
    m_prefs.setValue(QStringLiteral("new_project_schema"), m_newSchema->currentData().toString());
    m_prefs.setValue(QStringLiteral("large_ifc_mb"), m_largeIfc->value());
    m_prefs.setValue(QStringLiteral("auto_version"), m_autoVersion->currentData().toString());
    m_prefs.setValue(QStringLiteral("auto_version_every"), m_autoEvery->value());
    m_prefs.setValue(QStringLiteral("recovery_minutes"), m_recovery->value());
    m_prefs.setValue(QStringLiteral("drawing_timeout"), m_drawingTimeout->value());
    m_prefs.setValue(QStringLiteral("drawing_hlr"), m_drawingHlr->currentData().toString());
    m_prefs.setValue(QStringLiteral("scroll_navigation"), m_scrollMode->currentData().toString());
    m_prefs.setValue(QStringLiteral("tracker"), m_tracker->currentData().toString());
    m_prefs.setValue(QStringLiteral("angle_mode"), m_angleMode->currentData().toString());
    m_prefs.setValue(QStringLiteral("typed_length_unit"), m_typedLength->currentData().toString());
    m_prefs.setValue(QStringLiteral("tab_annotations"), m_tabAnnotations->isChecked());
    m_prefs.setValue(QStringLiteral("panels_shrink_first"), m_panelsShrink->isChecked());
    m_prefs.setValue(QStringLiteral("field_of_view"), double(m_fieldOfView->value()));
    m_prefs.setValue(QStringLiteral("north_arrow"), m_northArrow->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_levels"), m_titleLevels->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_cut"), m_titleCut->isChecked());
    m_prefs.setValue(QStringLiteral("title_bar_versions"), m_titleVersions->isChecked());
    m_prefs.setValue(QStringLiteral("select_similar_scope"), m_selectSimilar->currentData().toString());
    m_prefs.setValue(QStringLiteral("box_selection"), m_boxSelection->currentData().toString());
    m_prefs.setValue(QStringLiteral("split_join"), m_splitJoin->isChecked());
    m_prefs.setValue(QStringLiteral("merge_props"), m_mergeProps->currentData().toString());
    m_prefs.setValue(QStringLiteral("mesh_vertex_snaps"), m_meshVertexSnaps->isChecked());
    m_prefs.setValue(QStringLiteral("keep_rectangles_rectangular"), m_keepRectangles->isChecked());
    m_prefs.setValue(QStringLiteral("underlay_opacity"), double(m_underlayOpacity->value()) / 100.0);
    m_prefs.setValue(QStringLiteral("underlay_greyscale"), m_underlayGrey->isChecked());
    m_prefs.setValue(QStringLiteral("underlay_tint"), m_underlayTint->text().trimmed());
    m_prefs.setValue(QStringLiteral("underlay_layer_per_file"), m_underlayLayerPerFile->isChecked());
    const QString assistantProvider = m_assistantProvider->currentData().toString();
    m_prefs.setValue(QStringLiteral("assistant_provider"), assistantProvider);
    m_prefs.setValue(QStringLiteral("assistant_model"), m_assistantModel->text().trimmed());
    m_prefs.setValue(QStringLiteral("assistant_base_url"), m_assistantBaseUrl->text().trimmed());
    m_prefs.setValue(QStringLiteral("git_server_url"), m_gitServerUrl->text().trimmed());
    m_prefs.setValue(QStringLiteral("git_remote_name"), m_gitRemoteName->text().trimmed());
    m_prefs.setValue(QStringLiteral("git_username"), m_gitUsername->text().trimmed());
    m_prefs.setValue(QStringLiteral("git_fetch_on_open"), m_gitFetchOnOpen->isChecked());
    m_prefs.setValue(QStringLiteral("git_fetch_minutes"), m_gitFetchMinutes->value());
    m_prefs.setValue(QStringLiteral("git_push_after_save"), m_gitPushAfterSave->isChecked());
    m_prefs.setValue(QStringLiteral("git_pull_diverged"), m_gitPullDiverged->currentData().toString());
    m_prefs.setValue(QStringLiteral("git_push_tags"), m_gitPushTags->isChecked());
    m_prefs.setValue(QStringLiteral("http_proxy"), m_httpProxy->text().trimmed());
    m_prefs.setValue(QStringLiteral("plugin_folder"), m_pluginFolder->text().trimmed());
    m_prefs.setValue(QStringLiteral("console_on_startup"), m_consoleOnStartup->isChecked());
    m_prefs.setValue(QStringLiteral("update_channel"), m_updateChannel->currentData().toString());
    if (!m_assistantKey->text().trimmed().isEmpty()) {
        PythonEngine::instance().callJson("assistant_set_key",
            {assistantProvider, m_assistantKey->text().trimmed()});
        m_assistantKey->clear();
    }
    refreshGitTokenStatus();
}

bool PreferencesDialog::validate()
{
    const QString token = m_gitToken->text().trimmed();
    if (token.isEmpty())
        return true;
    const QString host = hostForUrl(m_gitServerUrl->text());
    if (host.isEmpty()) {
        QMessageBox::warning(this, tr("Preferences"),
            tr("Set the default NicGit server before saving a token for it."));
        m_sections->setCurrentRow(5); // Git and sync
        return false;
    }
    if (PythonEngine::instance().isRunning()) {
        const QJsonObject r = PythonEngine::instance().callJson("git_set_token", {host, token}).object();
        if (!r.value("ok").toBool()) {
            QMessageBox::warning(this, tr("Preferences"),
                r.value("error").toString().isEmpty()
                    ? tr("The token could not be stored in the operating system's credential store.")
                    : r.value("error").toString());
            return false;
        }
        m_gitToken->clear();
    }
    return true;
}

void PreferencesDialog::accept()
{
    if (!validate())
        return;
    apply();
    QDialog::accept();
}

void PreferencesDialog::refreshGitTokenStatus()
{
    if (!m_gitTokenStatus)
        return;
    const QString host = hostForUrl(m_gitServerUrl->text());
    if (host.isEmpty()) {
        m_gitTokenStatus->setText(tr("Add the default server to store a token for it."));
        if (m_gitForgetToken)
            m_gitForgetToken->setEnabled(false);
        return;
    }
    if (!m_gitToken->text().trimmed().isEmpty()) {
        m_gitTokenStatus->setText(tr("A new token for %1 is saved when you press OK.").arg(host));
        if (m_gitForgetToken)
            m_gitForgetToken->setEnabled(false);
        return;
    }
    if (!PythonEngine::instance().isRunning()) {
        m_gitTokenStatus->setText(tr("The token is stored per server."));
        if (m_gitForgetToken)
            m_gitForgetToken->setEnabled(false);
        return;
    }
    const QJsonObject r = PythonEngine::instance().callJson("git_has_token", {host}).object();
    const bool stored = r.value("stored").toBool();
    m_gitTokenStatus->setText(stored ? tr("A token is stored for %1.").arg(host)
                                     : tr("No token stored for %1 yet.").arg(host));
    if (m_gitForgetToken)
        m_gitForgetToken->setEnabled(stored);
}

QString PreferencesDialog::hostForUrl(const QString& url)
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
    return {};
}

} // namespace kimbim
