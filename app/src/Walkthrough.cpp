// SPDX-License-Identifier: GPL-3.0-or-later
// D249: View > Walkthrough... (Archicad's Fly-through). The user places cameras by moving the 3D view
// and adding it, previews the path in the view, saves it with the project and renders a video: one
// frame per camera from walkthrough.path_frames, joined by ffmpeg (walkthrough.encode_video). The
// dialog is modeless so the 3D view stays usable while the path is built.

#include "MainWindow.h"
#include "StatusStrip.h"
#include "Viewport.h"
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QProgressDialog>
#include <QPushButton>
#include <QSpinBox>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>
#include <Graphic3d_Camera.hxx>
#include <V3d_View.hxx>
#include <memory>

namespace kimbim {

namespace {

QJsonArray xyz(const gp_Pnt& p)
{
    return QJsonArray{p.X(), p.Y(), p.Z()};
}

QString xyzText(const QJsonArray& a)
{
    return QStringLiteral("%1, %2, %3").arg(a[0].toDouble(), 0, 'f', 2).arg(a[1].toDouble(), 0, 'f', 2)
        .arg(a[2].toDouble(), 0, 'f', 2);
}

gp_Pnt point(const QJsonValue& v)
{
    const QJsonArray a = v.toArray();
    return a.size() == 3 ? gp_Pnt(a[0].toDouble(), a[1].toDouble(), a[2].toDouble()) : gp_Pnt();
}

} // namespace

void MainWindow::showWalkthroughCamera(const QJsonObject& camera)
{
    if (!m_viewport)
        return;
    const QJsonArray up = camera.value("up").toArray();
    const gp_Dir dir = up.size() == 3 ? gp_Dir(up[0].toDouble(), up[1].toDouble(), up[2].toDouble()) : gp_Dir(0, 0, 1);
    m_viewport->setCamera(point(camera.value("eye")), point(camera.value("target")), dir, true,
        camera.value("fov").toDouble(60.0), 1.0);
}

void MainWindow::walkthroughDialog()
{
    if (m_walkthroughDialog) {
        m_walkthroughDialog->raise();
        m_walkthroughDialog->activateWindow();
        return;
    }
    if (!m_viewport) {
        m_status->showMessage(tr("Open a 3D view first"));
        return;
    }
    auto* dialog = new QDialog(this);
    dialog->setObjectName(QStringLiteral("walkthroughDialog"));
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle(tr("Walkthrough"));
    m_walkthroughDialog = dialog;

    auto* layout = new QVBoxLayout(dialog);
    auto* nameRow = new QHBoxLayout;
    auto* names = new QComboBox(dialog);
    names->setObjectName(QStringLiteral("walkthroughName"));
    names->setEditable(true);
    names->setInsertPolicy(QComboBox::NoInsert);
    names->setMinimumWidth(220);
    auto* remove = new QPushButton(tr("Delete"), dialog);
    remove->setObjectName(QStringLiteral("walkthroughDelete"));
    nameRow->addWidget(new QLabel(tr("Walkthrough:"), dialog));
    nameRow->addWidget(names, 1);
    nameRow->addWidget(remove);
    layout->addLayout(nameRow);

    auto* table = new QTableWidget(0, 3, dialog);
    table->setObjectName(QStringLiteral("walkthroughCameras"));
    table->setHorizontalHeaderLabels({tr("Eye (m)"), tr("Looks at (m)"), tr("Field of view")});
    table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setToolTip(tr("The cameras in order; the video moves through them at an even speed"));
    layout->addWidget(table, 1);

    auto* cameraRow = new QHBoxLayout;
    auto* add = new QPushButton(tr("Add current view"), dialog);
    add->setObjectName(QStringLiteral("walkthroughAdd"));
    add->setToolTip(tr("Add the 3D view's camera after the selected one"));
    auto* replace = new QPushButton(tr("Replace"), dialog);
    replace->setToolTip(tr("Replace the selected camera with the 3D view's camera"));
    auto* removeCamera = new QPushButton(tr("Remove"), dialog);
    auto* upButton = new QToolButton(dialog);
    upButton->setArrowType(Qt::UpArrow);
    upButton->setToolTip(tr("Move up"));
    auto* downButton = new QToolButton(dialog);
    downButton->setArrowType(Qt::DownArrow);
    downButton->setToolTip(tr("Move down"));
    auto* goTo = new QPushButton(tr("Go to"), dialog);
    goTo->setToolTip(tr("Show the selected camera in the 3D view"));
    for (QWidget* w : {static_cast<QWidget*>(add), static_cast<QWidget*>(replace), static_cast<QWidget*>(removeCamera),
                       static_cast<QWidget*>(upButton), static_cast<QWidget*>(downButton), static_cast<QWidget*>(goTo)})
        cameraRow->addWidget(w);
    cameraRow->addStretch(1);
    layout->addLayout(cameraRow);

    auto* form = new QFormLayout;
    auto* seconds = new QDoubleSpinBox(dialog);
    seconds->setObjectName(QStringLiteral("walkthroughSeconds"));
    seconds->setRange(0.1, 3600);
    seconds->setDecimals(1);
    seconds->setValue(10);
    seconds->setSuffix(tr(" s"));
    auto* fps = new QSpinBox(dialog);
    fps->setObjectName(QStringLiteral("walkthroughFps"));
    fps->setRange(1, 120);
    fps->setValue(25);
    fps->setSuffix(tr(" frames/s"));
    auto* smooth = new QCheckBox(tr("Smooth path through the cameras"), dialog);
    smooth->setObjectName(QStringLiteral("walkthroughSmooth"));
    smooth->setChecked(true);
    auto* closed = new QCheckBox(tr("Return to the first camera"), dialog);
    closed->setObjectName(QStringLiteral("walkthroughClosed"));
    auto* width = new QSpinBox(dialog);
    width->setObjectName(QStringLiteral("walkthroughWidth"));
    width->setRange(128, 7680);
    width->setSingleStep(2);
    width->setValue(1280);
    auto* height = new QSpinBox(dialog);
    height->setObjectName(QStringLiteral("walkthroughHeight"));
    height->setRange(128, 7680);
    height->setSingleStep(2);
    height->setValue(720);
    auto* sizeRow = new QHBoxLayout;
    sizeRow->addWidget(width);
    sizeRow->addWidget(new QLabel(QStringLiteral("×"), dialog));
    sizeRow->addWidget(height);
    sizeRow->addWidget(new QLabel(tr("px"), dialog));
    sizeRow->addStretch(1);
    auto* output = new QLineEdit(dialog);
    output->setObjectName(QStringLiteral("walkthroughOutput"));
    output->setPlaceholderText(tr("walkthrough.mp4"));
    auto* browse = new QToolButton(dialog);
    browse->setText(tr("..."));
    auto* outputRow = new QHBoxLayout;
    outputRow->addWidget(output, 1);
    outputRow->addWidget(browse);
    auto* keepFrames = new QCheckBox(tr("Keep the frames (PNG) next to the video"), dialog);
    keepFrames->setObjectName(QStringLiteral("walkthroughKeepFrames"));
    auto* info = new QLabel(dialog);
    info->setObjectName(QStringLiteral("walkthroughInfo"));
    form->addRow(tr("Duration:"), seconds);
    form->addRow(tr("Frame rate:"), fps);
    form->addRow(QString(), smooth);
    form->addRow(QString(), closed);
    form->addRow(tr("Video size:"), sizeRow);
    form->addRow(tr("Video file:"), outputRow);
    form->addRow(QString(), keepFrames);
    form->addRow(QString(), info);
    layout->addLayout(form);

    auto* buttons = new QHBoxLayout;
    auto* save = new QPushButton(tr("Save"), dialog);
    save->setObjectName(QStringLiteral("walkthroughSave"));
    save->setToolTip(tr("Save the walkthrough with the project (one undo step)"));
    auto* preview = new QPushButton(tr("Preview"), dialog);
    preview->setObjectName(QStringLiteral("walkthroughPreview"));
    preview->setCheckable(true);
    preview->setToolTip(tr("Play the path in the 3D view"));
    auto* render = new QPushButton(tr("Render video..."), dialog);
    render->setObjectName(QStringLiteral("walkthroughRender"));
    auto* close = new QPushButton(tr("Close"), dialog);
    buttons->addWidget(save);
    buttons->addWidget(preview);
    buttons->addStretch(1);
    buttons->addWidget(render);
    buttons->addWidget(close);
    layout->addLayout(buttons);
    dialog->resize(640, 560);

    // ------------------------------------------------------------ state
    auto cameras = std::make_shared<QJsonArray>();
    auto refreshTable = [=] {
        const int keep = table->currentRow();
        table->setRowCount(int(cameras->size()));
        for (int i = 0; i < cameras->size(); ++i) {
            const QJsonObject c = (*cameras)[i].toObject();
            table->setItem(i, 0, new QTableWidgetItem(xyzText(c.value("eye").toArray())));
            table->setItem(i, 1, new QTableWidgetItem(xyzText(c.value("target").toArray())));
            table->setItem(i, 2, new QTableWidgetItem(QStringLiteral("%1°").arg(c.value("fov").toDouble(60), 0, 'f', 0)));
        }
        table->setCurrentCell(qBound(-1, keep, int(cameras->size()) - 1), 0);
    };
    auto data = [=] {
        return QJsonObject{{"cameras", *cameras}, {"seconds", seconds->value()}, {"fps", fps->value()},
            {"smooth", smooth->isChecked()}, {"closed", closed->isChecked()},
            {"size", QJsonArray{width->value() & ~1, height->value() & ~1}}};
    };
    auto updateInfo = [=] {
        const int frames = qMax(2, int(qRound(seconds->value() * fps->value()))) + (closed->isChecked() ? 0 : 1);
        info->setText(tr("%n camera(s), %1 frames", nullptr, int(cameras->size())).arg(frames));
    };
    auto reloadNames = [=](const QString& select) {
        const QSignalBlocker block(names);
        names->clear();
        for (const auto& v : bridge("walkthroughs").value("walkthroughs").toArray())
            names->addItem(v.toObject().value("name").toString());
        names->setCurrentText(select);
    };
    auto load = [=](const QString& name) {
        for (const auto& v : bridge("walkthroughs").value("walkthroughs").toArray()) {
            const QJsonObject w = v.toObject();
            if (w.value("name").toString() != name)
                continue;
            *cameras = w.value("cameras").toArray();
            seconds->setValue(w.value("seconds").toDouble(10));
            fps->setValue(w.value("fps").toInt(25));
            smooth->setChecked(w.value("smooth").toBool(true));
            closed->setChecked(w.value("closed").toBool(false));
            const QJsonArray size = w.value("size").toArray();
            if (size.size() == 2) {
                width->setValue(size[0].toInt(1280));
                height->setValue(size[1].toInt(720));
            }
            refreshTable();
            updateInfo();
            return;
        }
    };
    auto currentCamera = [this] {
        if (m_viewport->isPlanView())
            m_viewport->set3DView();
        const Handle(Graphic3d_Camera) cam = m_viewport->view()->Camera();
        return QJsonObject{{"eye", xyz(cam->Eye())}, {"target", xyz(cam->Center())},
            {"fov", cam->IsOrthographic() ? 60.0 : cam->FOVy()}};
    };

    // ------------------------------------------------------------ cameras
    connect(add, &QPushButton::clicked, dialog, [=] {
        const int at = table->currentRow() < 0 ? int(cameras->size()) : table->currentRow() + 1;
        cameras->insert(at, currentCamera());
        refreshTable();
        table->setCurrentCell(at, 0);
        updateInfo();
    });
    connect(replace, &QPushButton::clicked, dialog, [=] {
        const int row = table->currentRow();
        if (row < 0)
            return;
        (*cameras)[row] = currentCamera();
        refreshTable();
    });
    connect(removeCamera, &QPushButton::clicked, dialog, [=] {
        const int row = table->currentRow();
        if (row < 0)
            return;
        cameras->removeAt(row);
        refreshTable();
        updateInfo();
    });
    auto move = [=](int delta) {
        const int row = table->currentRow();
        const int to = row + delta;
        if (row < 0 || to < 0 || to >= cameras->size())
            return;
        const QJsonValue v = (*cameras)[row];
        (*cameras)[row] = (*cameras)[to];
        (*cameras)[to] = v;
        refreshTable();
        table->setCurrentCell(to, 0);
    };
    connect(upButton, &QToolButton::clicked, dialog, [=] { move(-1); });
    connect(downButton, &QToolButton::clicked, dialog, [=] { move(1); });
    auto goToRow = [=](int row) {
        if (row >= 0 && row < cameras->size()) {
            QJsonObject c = (*cameras)[row].toObject();
            showWalkthroughCamera(c);
        }
    };
    connect(goTo, &QPushButton::clicked, dialog, [=] { goToRow(table->currentRow()); });
    connect(table, &QTableWidget::cellDoubleClicked, dialog, [=](int row, int) { goToRow(row); });
    connect(seconds, &QDoubleSpinBox::valueChanged, dialog, updateInfo);
    connect(fps, &QSpinBox::valueChanged, dialog, updateInfo);
    connect(closed, &QCheckBox::toggled, dialog, updateInfo);

    // ------------------------------------------------------------ saved walkthroughs
    connect(names, &QComboBox::activated, dialog, [=](int index) { load(names->itemText(index)); });
    connect(save, &QPushButton::clicked, dialog, [=] {
        const QString name = names->currentText().trimmed();
        const QJsonObject r = bridge("save_walkthrough",
            {name, QString::fromUtf8(QJsonDocument(data()).toJson(QJsonDocument::Compact))});
        if (!r.value("ok").toBool()) {
            showError(tr("Walkthrough"), r.value("error").toString());
            return;
        }
        afterEdit(r);
        reloadNames(name);
        m_status->showMessage(tr("Walkthrough %1 saved (%n frame(s))", nullptr, r.value("frames").toInt()).arg(name));
    });
    connect(remove, &QPushButton::clicked, dialog, [=] {
        const QString name = names->currentText().trimmed();
        if (names->findText(name) < 0)
            return;
        if (QMessageBox::question(dialog, tr("Walkthrough"), tr("Delete the walkthrough %1?").arg(name))
            != QMessageBox::Yes)
            return;
        const QJsonObject r = bridge("delete_walkthrough", {name});
        if (!r.value("ok").toBool()) {
            showError(tr("Walkthrough"), r.value("error").toString());
            return;
        }
        afterEdit(r);
        reloadNames(QString());
    });

    // ------------------------------------------------------------ preview and render
    auto frames = [=]() -> QJsonObject {
        const QJsonObject r = bridge("walkthrough_frames",
            {QString::fromUtf8(QJsonDocument(data()).toJson(QJsonDocument::Compact))});
        if (!r.value("ok").toBool())
            showError(tr("Walkthrough"), r.value("error").toString());
        return r;
    };
    auto* timer = new QTimer(dialog);
    auto playing = std::make_shared<QJsonArray>();
    auto playIndex = std::make_shared<int>(0);
    connect(timer, &QTimer::timeout, dialog, [=] {
        if (*playIndex >= playing->size()) {
            timer->stop();
            preview->setChecked(false);
            return;
        }
        showWalkthroughCamera((*playing)[(*playIndex)++].toObject());
    });
    connect(preview, &QPushButton::toggled, dialog, [=](bool on) {
        if (!on) {
            timer->stop();
            return;
        }
        const QJsonObject r = frames();
        if (!r.value("ok").toBool()) {
            preview->setChecked(false);
            return;
        }
        *playing = r.value("frames").toArray();
        *playIndex = 0;
        timer->start(qMax(1, 1000 / qMax(1, r.value("fps").toInt(25))));
    });
    connect(browse, &QToolButton::clicked, dialog, [=] {
        const QString chosen = QFileDialog::getSaveFileName(dialog, tr("Walkthrough video"), output->text(),
            tr("MP4 video (*.mp4);;QuickTime video (*.mov);;WebM video (*.webm)"));
        if (!chosen.isEmpty())
            output->setText(chosen);
    });
    connect(render, &QPushButton::clicked, dialog, [=] {
        preview->setChecked(false);
        if (!bridge("ffmpeg_state").value("found").toBool()) {
            showError(tr("Walkthrough"), tr("ffmpeg was not found. Install it (it must be on PATH) or set "
                                            "KIMBIM_FFMPEG to the program, then render again."));
            return;
        }
        QString out = output->text().trimmed();
        if (out.isEmpty()) {
            out = QFileDialog::getSaveFileName(dialog, tr("Walkthrough video"), QStringLiteral("walkthrough.mp4"),
                tr("MP4 video (*.mp4);;QuickTime video (*.mov);;WebM video (*.webm)"));
            if (out.isEmpty())
                return;
            output->setText(out);
        }
        const QJsonObject r = frames();
        if (!r.value("ok").toBool())
            return;
        const QJsonArray list = r.value("frames").toArray();
        const QFileInfo target(out);
        QTemporaryDir temp;
        const QString folder = keepFrames->isChecked()
            ? target.dir().filePath(target.completeBaseName() + QStringLiteral("-frames")) : temp.path();
        QDir().mkpath(folder);
        const Handle(Graphic3d_Camera) saved = new Graphic3d_Camera(m_viewport->view()->Camera());
        const bool wasPerspective = !saved->IsOrthographic();
        QProgressDialog progress(tr("Rendering the walkthrough..."), tr("Cancel"), 0, int(list.size()), dialog);
        progress.setWindowModality(Qt::WindowModal);
        int written = 0;
        for (const auto& value : list) {
            if (progress.wasCanceled())
                break;
            showWalkthroughCamera(value.toObject());
            progress.setLabelText(tr("Frame %1 of %2").arg(written + 1).arg(list.size()));
            const QImage image = m_viewport->renderImage(width->value() & ~1, height->value() & ~1);
            const QString file = QDir(folder).filePath(QStringLiteral("frame-%1.png").arg(written, 5, 10, QLatin1Char('0')));
            if (image.isNull() || !image.save(file))
                break;
            progress.setValue(++written);
            QApplication::processEvents();
        }
        m_viewport->setCamera(saved->Eye(), saved->Center(), saved->Up(), wasPerspective, saved->FOVy(), saved->Scale());
        if (written < list.size()) {
            m_status->showMessage(tr("Walkthrough stopped after %n frame(s)", nullptr, written));
            return;
        }
        const QJsonObject e = bridge("encode_walkthrough_video", {folder, QString::number(r.value("fps").toInt(25)), out});
        if (!e.value("ok").toBool()) {
            showError(tr("Walkthrough"), e.value("error").toString());
            return;
        }
        m_status->showMessage(tr("Walkthrough video written to %1").arg(QDir::toNativeSeparators(out)));
    });
    connect(close, &QPushButton::clicked, dialog, &QDialog::close);

    reloadNames(QString());
    if (names->count() > 0) {
        names->setCurrentIndex(0);
        load(names->itemText(0));
    } else {
        names->setCurrentText(tr("Walkthrough 1"));
    }
    updateInfo();
    dialog->show();
}

} // namespace kimbim
