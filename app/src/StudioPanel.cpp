// SPDX-License-Identifier: GPL-3.0-or-later
#include "StudioPanel.h"

#include "PythonEngine.h"

#include <QAction>
#include <QCheckBox>
#include <QComboBox>
#include <QHBoxLayout>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QKeySequence>
#include <QLabel>
#include <QMap>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QShowEvent>
#include <QSignalBlocker>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTextDocument>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

namespace kimbim {

namespace {
QString escaped(const QString& text)
{
    return text.toHtmlEscaped().replace(QLatin1Char('\n'), QStringLiteral("<br>"));
}

bool live(const QString& state)
{
    return state == QLatin1String("starting") || state == QLatin1String("working")
        || state == QLatin1String("waiting") || state == QLatin1String("paused");
}
} // namespace

StudioPanel::StudioPanel(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("studioPanel"));
    setMinimumSize(0, 0);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);

    auto* top = new QHBoxLayout;
    m_sessions = new QComboBox(this);
    m_sessions->setObjectName(QStringLiteral("studioSessions"));
    m_sessions->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    m_sessions->setMinimumContentsLength(12);
    m_effort = new QComboBox(this);
    m_effort->setObjectName(QStringLiteral("studioEffort"));
    m_effort->addItem(tr("Medium effort"), QStringLiteral("medium"));
    m_effort->addItem(tr("High effort"), QStringLiteral("high"));
    m_effort->addItem(tr("Highest effort"), QStringLiteral("xhigh"));
    m_effort->setCurrentIndex(1);
    m_effort->setToolTip(tr("How hard a new agent thinks before it acts"));
    m_start = new QPushButton(tr("Start"), this);
    m_start->setObjectName(QStringLiteral("studioStart"));
    m_start->setToolTip(tr("Start a studio agent with the text below as its brief"));
    top->addWidget(m_sessions, 1);
    top->addWidget(m_effort);
    top->addWidget(m_start);
    layout->addLayout(top);

    m_view = new QTextBrowser(this);
    m_view->setObjectName(QStringLiteral("studioFeed"));
    m_view->setOpenExternalLinks(true);
    m_view->setMinimumSize(0, 0);
    m_view->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    layout->addWidget(m_view, 1);

    m_input = new QPlainTextEdit(this);
    m_input->setObjectName(QStringLiteral("studioInput"));
    m_input->setPlaceholderText(tr("A brief to start an agent, or a message to the running one "
                                   "(Ctrl+Enter sends)"));
    m_input->setMaximumHeight(90);
    layout->addWidget(m_input);

    auto* row = new QHBoxLayout;
    m_asTask = new QCheckBox(tr("As a small task"), this);
    m_asTask->setObjectName(QStringLiteral("studioAsTask"));
    m_asTask->setToolTip(tr("A helper does it in parallel; the agent carries on with its plan"));
    m_send = new QPushButton(tr("Send"), this);
    m_send->setObjectName(QStringLiteral("studioSend"));
    m_pause = new QPushButton(tr("Pause"), this);
    m_pause->setObjectName(QStringLiteral("studioPause"));
    m_stop = new QPushButton(tr("Stop"), this);
    m_stop->setObjectName(QStringLiteral("studioStop"));
    row->addWidget(m_asTask);
    row->addStretch(1);
    row->addWidget(m_pause);
    row->addWidget(m_stop);
    row->addWidget(m_send);
    layout->addLayout(row);
    m_state = new QLabel(this);
    m_state->setObjectName(QStringLiteral("studioState"));
    layout->addWidget(m_state);

    connect(m_sessions, &QComboBox::activated, this, &StudioPanel::selectSession);
    connect(m_start, &QPushButton::clicked, this, &StudioPanel::startSession);
    connect(m_send, &QPushButton::clicked, this, &StudioPanel::send);
    connect(m_pause, &QPushButton::clicked, this, [this] {
        control(m_lastState == QLatin1String("paused") ? QStringLiteral("resume") : QStringLiteral("pause"));
    });
    connect(m_stop, &QPushButton::clicked, this, [this] {
        if (live(m_lastState))
            control(QStringLiteral("stop"));
        else if (!m_session.isEmpty()) { // a stopped agent: start it again from its plan and notes
            const QJsonObject r = call("studio_resume", {m_session});
            if (!r.value(QStringLiteral("ok")).toBool())
                showProblem(r);
        }
    });
    auto* shortcut = new QAction(this);
    shortcut->setShortcut(QKeySequence(Qt::CTRL | Qt::Key_Return));
    shortcut->setShortcutContext(Qt::WidgetShortcut);
    m_input->addAction(shortcut);
    connect(shortcut, &QAction::triggered, this, [this] {
        if (m_session.isEmpty() || !live(m_lastState))
            startSession();
        else
            send();
    });

    m_timer = new QTimer(this);
    m_timer->setInterval(700);
    connect(m_timer, &QTimer::timeout, this, &StudioPanel::poll);
    updateState({});
    append(QStringLiteral("<p style='color:#777'>%1</p>")
               .arg(escaped(tr("A studio agent designs and builds with you in a long session: write a brief and "
                               "press Start. It works in this model while you do; send it messages or small tasks "
                               "at any time. The same agents are reachable with `kimbim studio`."))));
}

QJsonObject StudioPanel::call(const char* fn, const QStringList& args)
{
    QString problem;
    const QJsonObject answer = PythonEngine::instance().callJson(fn, args, &problem).object();
    if (!problem.isEmpty())
        return {{QStringLiteral("ok"), false},
                {QStringLiteral("error"), QJsonObject{{QStringLiteral("message"), problem}}}};
    return answer;
}

void StudioPanel::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    refreshSessions();
}

void StudioPanel::refreshSessions()
{
    const QJsonObject answer = call("studio_list");
    const QJsonArray rows = answer.value(QStringLiteral("result")).toObject().value(QStringLiteral("sessions")).toArray();
    QSignalBlocker block(m_sessions);
    m_sessions->clear();
    m_sessions->addItem(tr("New agent…"), QString());
    int keep = 0;
    for (const QJsonValue& v : rows) {
        const QJsonObject row = v.toObject();
        const QString id = row.value(QStringLiteral("session")).toString();
        m_sessions->addItem(QStringLiteral("%1 — %2").arg(row.value(QStringLiteral("title")).toString(),
                                                          row.value(QStringLiteral("state")).toString()),
                            id);
        if (id == m_session)
            keep = m_sessions->count() - 1;
    }
    if (keep == 0 && !m_session.isEmpty())
        m_session.clear();
    if (keep == 0 && m_session.isEmpty()) { // follow the newest running agent
        for (int i = 1; i < m_sessions->count(); ++i) {
            if (m_sessions->itemText(i).endsWith(QLatin1String("working"))
                || m_sessions->itemText(i).endsWith(QLatin1String("waiting"))) {
                keep = i;
                break;
            }
        }
    }
    m_sessions->setCurrentIndex(keep);
    if (keep > 0 && m_sessions->itemData(keep).toString() != m_session)
        selectSession(keep);
    if (!m_session.isEmpty())
        m_timer->start();
}

void StudioPanel::selectSession(int index)
{
    m_session = m_sessions->itemData(index).toString();
    m_view->clear();
    m_next = 0;
    m_images = 0;
    m_lastState.clear();
    if (m_session.isEmpty()) {
        m_timer->stop();
        updateState({});
        return;
    }
    poll();
    m_timer->start();
}

void StudioPanel::poll()
{
    if (m_session.isEmpty())
        return;
    const QJsonObject answer = call("studio_feed", {m_session, QString::number(m_next)});
    if (!answer.value(QStringLiteral("ok")).toBool())
        return;
    const QJsonObject result = answer.value(QStringLiteral("result")).toObject();
    const QJsonArray entries = result.value(QStringLiteral("entries")).toArray();
    for (const QJsonValue& v : entries)
        render(v.toObject());
    m_next = result.value(QStringLiteral("next")).toInt(m_next);
    updateState(result.value(QStringLiteral("state")).toObject());
}

void StudioPanel::render(const QJsonObject& entry)
{
    const QString role = entry.value(QStringLiteral("role")).toString();
    const QString agent = entry.value(QStringLiteral("agent")).toString();
    const QString who = agent.isEmpty() || agent == QLatin1String("main") ? QString()
                                                                         : QStringLiteral("[%1] ").arg(agent);
    const QString text = entry.value(QStringLiteral("text")).toString();
    if (role == QLatin1String("tool")) {
        const bool ok = entry.value(QStringLiteral("ok")).toBool();
        append(QStringLiteral("<p style='color:%1;margin:0'>%2%3 %4</p>")
                   .arg(ok ? QStringLiteral("#2e7d32") : QStringLiteral("#c62828"), escaped(who),
                        ok ? QStringLiteral("✓") : QStringLiteral("✗"),
                        escaped(entry.value(QStringLiteral("summary")).toString())));
        const QString snapshot = entry.value(QStringLiteral("snapshot")).toString();
        if (!snapshot.isEmpty())
            addImage(snapshot);
    } else if (role == QLatin1String("user")) {
        const QString kind = entry.value(QStringLiteral("kind")).toString();
        append(QStringLiteral("<p><b style='color:#1f4e79'>%1</b><br>%2</p>")
                   .arg(kind == QLatin1String("task") ? tr("You (small task)") : tr("You"), escaped(text)));
    } else if (role == QLatin1String("assistant")) {
        append(QStringLiteral("<p><b>%1%2</b><br>%3</p>").arg(escaped(who), tr("Agent"), escaped(text)));
    } else if (role == QLatin1String("thinking")) {
        append(QStringLiteral("<p style='color:#888;margin:0'><i>%1%2</i></p>")
                   .arg(escaped(who), escaped(text.left(600))));
    } else if (role == QLatin1String("question")) {
        append(QStringLiteral("<p style='background:#fff4ce'><b>%1%2</b><br>%3</p>")
                   .arg(escaped(who), tr("Question for you"), escaped(text)));
    } else if (role == QLatin1String("note")) {
        append(QStringLiteral("<p style='color:#555;margin:0'>%1%2 %3</p>").arg(escaped(who), tr("Note:"), escaped(text)));
    } else if (role == QLatin1String("status")) {
        append(QStringLiteral("<p style='color:#777;margin:0'>— %1%2</p>").arg(escaped(who), escaped(text)));
    }
}

void StudioPanel::append(const QString& html)
{
    QTextCursor cursor(m_view->document());
    cursor.movePosition(QTextCursor::End);
    cursor.insertHtml(html);
    cursor.insertBlock();
    m_view->setTextCursor(cursor);
    m_view->ensureCursorVisible();
}

void StudioPanel::addImage(const QString& path)
{
    const QImage image(path);
    if (image.isNull())
        return;
    const QUrl uri(QStringLiteral("kimbim-studio://%1").arg(++m_images));
    m_view->document()->addResource(QTextDocument::ImageResource, uri, image);
    append(QStringLiteral("<p><img src='%1' width='420'></p>").arg(uri.toString()));
}

void StudioPanel::showProblem(const QJsonObject& answer)
{
    // in the panel, not a modal box: the architect keeps working while the agent runs
    const QJsonObject e = answer.value(QStringLiteral("error")).toObject();
    QString text = e.value(QStringLiteral("message")).toString();
    const QString hint = e.value(QStringLiteral("hint")).toString();
    if (!hint.isEmpty())
        text += QStringLiteral(" ") + hint;
    m_state->setText(tr("Could not do that: %1").arg(text.isEmpty() ? tr("unknown error") : text));
}

void StudioPanel::send()
{
    const QString text = m_input->toPlainText().trimmed();
    if (text.isEmpty() || m_session.isEmpty())
        return;
    const QJsonObject r = call("studio_send", {m_session, m_asTask->isChecked() ? QStringLiteral("task")
                                                                                 : QStringLiteral("say"), text});
    if (!r.value(QStringLiteral("ok")).toBool()) {
        showProblem(r);
        return;
    }
    m_input->clear();
    m_asTask->setChecked(false);
    poll();
}

void StudioPanel::startSession()
{
    const QString brief = m_input->toPlainText().trimmed();
    if (brief.isEmpty()) {
        m_input->setFocus();
        m_state->setText(tr("Write a brief first: what to design, where, for whom."));
        return;
    }
    const QJsonObject r = call("studio_start", {brief, m_effort->currentData().toString()});
    if (!r.value(QStringLiteral("ok")).toBool()) {
        showProblem(r);
        return;
    }
    m_session = r.value(QStringLiteral("result")).toObject().value(QStringLiteral("session")).toString();
    m_input->clear();
    refreshSessions();
}

void StudioPanel::control(const QString& kind)
{
    if (m_session.isEmpty())
        return;
    call("studio_send", {m_session, kind, QString()});
    poll();
}

void StudioPanel::updateState(const QJsonObject& state)
{
    const QString s = state.value(QStringLiteral("state")).toString();
    const bool running = live(s);
    m_send->setEnabled(!m_session.isEmpty());
    m_pause->setEnabled(running);
    m_pause->setText(s == QLatin1String("paused") ? tr("Resume") : tr("Pause"));
    m_stop->setEnabled(!m_session.isEmpty());
    m_stop->setText(running || m_session.isEmpty() ? tr("Stop") : tr("Restart"));
    m_start->setEnabled(true);
    if (s != m_lastState && !m_lastState.isEmpty() && !s.isEmpty())
        refreshSessions(); // the picker shows each agent's state
    m_lastState = s;
    if (m_session.isEmpty()) {
        m_state->setText(tr("No agent selected"));
        return;
    }
    const QMap<QString, QString> names{{QStringLiteral("starting"), tr("Starting…")},
                                       {QStringLiteral("working"), tr("Working")},
                                       {QStringLiteral("waiting"), tr("Waiting for you")},
                                       {QStringLiteral("paused"), tr("Paused")},
                                       {QStringLiteral("stopped"), tr("Stopped")},
                                       {QStringLiteral("failed"), tr("Failed")},
                                       {QStringLiteral("done"), tr("Finished")}};
    QString line = names.value(s, s);
    const int calls = state.value(QStringLiteral("calls")).toInt();
    if (calls)
        line += tr(" · %n tool call(s)", nullptr, calls);
    const QString error = state.value(QStringLiteral("error")).toString();
    if (!error.isEmpty() && !running)
        line += QStringLiteral(" · ") + error.left(160);
    m_state->setText(line);
    if (!running && s != QLatin1String("starting"))
        m_timer->setInterval(3000); // keep an eye on it (a restart), but slowly
    else
        m_timer->setInterval(700);
}

} // namespace kimbim
