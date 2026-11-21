// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QWidget>

class QCheckBox;
class QComboBox;
class QLabel;
class QPlainTextEdit;
class QPushButton;
class QShowEvent;
class QTextBrowser;
class QTimer;

namespace kimbim {

// D252: the Studio panel. Long-running studio agents of the open project: start one from a brief, watch its
// feed live (messages, thinking, tool calls, snapshots, questions, helpers), steer it with messages or small
// tasks while it works, pause, resume or stop it. The agent runs in its own process; its writes reach the model
// through the live session, so the views update as it builds.
class StudioPanel : public QWidget {
    Q_OBJECT
public:
    explicit StudioPanel(QWidget* parent = nullptr);
    void refreshSessions();
    QString sessionId() const { return m_session; }

protected:
    void showEvent(QShowEvent* event) override;

private:
    QJsonObject call(const char* fn, const QStringList& args = {});
    void selectSession(int index);
    void poll();
    void render(const QJsonObject& entry);
    void append(const QString& html);
    void addImage(const QString& path);
    void send();
    void startSession();
    void control(const QString& kind);
    void updateState(const QJsonObject& state);
    void showProblem(const QJsonObject& answer);

    QComboBox* m_sessions = nullptr;
    QPushButton* m_start = nullptr;
    QTextBrowser* m_view = nullptr;
    QPlainTextEdit* m_input = nullptr;
    QCheckBox* m_asTask = nullptr;
    QPushButton* m_send = nullptr;
    QPushButton* m_pause = nullptr;
    QPushButton* m_stop = nullptr;
    QComboBox* m_effort = nullptr;
    QLabel* m_state = nullptr;
    QTimer* m_timer = nullptr;
    QString m_session;
    QString m_lastState;
    int m_next = 0;
    int m_images = 0;
};

} // namespace kimbim
