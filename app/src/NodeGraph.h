// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// D238: the visual scripts as a node graph. Each node is an operation (massing, room, push/pull,
// numbers...); a wire from a node's output to another node's input feeds the first one's result (its
// new element, or its value) into that argument. Saving writes the nodes in dependency order as the
// script's steps (visual.save_graph), so the linear runner of D223 still runs it as one undo step.

#include <QDialog>
#include <QGraphicsEllipseItem>
#include <QGraphicsRectItem>
#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QMap>
#include <QPointF>
#include <QVector>

#include <functional>

class QComboBox;
class QGraphicsPathItem;
class QGraphicsScene;
class QGraphicsSimpleTextItem;
class QGraphicsView;
class QLineEdit;

namespace kimbim {

class NodeGraphDialog : public QDialog {
    Q_OBJECT
public:
    // `ops`: [{op, args: [names]}] (visual.pipeline_ops); `graph`: {nodes, links} (visual.steps_to_graph).
    NodeGraphDialog(const QJsonArray& ops, const QString& name, const QJsonObject& graph, QWidget* parent = nullptr);

    int addNode(const QString& op, QPointF pos, const QJsonObject& args = {}); // its id, or 0 for an unknown op
    bool link(int from, int to, const QString& arg); // false: unknown node or argument, or a self wire
    void unlink(int to, const QString& arg);
    void removeNode(int id);
    void setArg(int node, const QString& arg, const QJsonValue& value);
    QJsonObject graph() const;   // {nodes: [{id, op, args, x, y}], links: [{from, to, arg}]}
    QString name() const;
    int nodeCount() const { return int(m_nodes.size()); }
    int linkCount() const { return int(m_links.size()); }
    QGraphicsView* view() const { return m_view; }

    // The main window's save and run (they talk to the bridge); each returns an error or "".
    std::function<QString(const QString& name, const QJsonObject& graph)> onSave;
    std::function<QString(const QString& name)> onRun;

    // Scene interaction (also used by tests): a press on an output port starts a wire; a release over
    // an input port finishes it.
    bool startWire(QPointF scenePos);
    bool finishWire(QPointF scenePos);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    struct Node {
        int id = 0;
        QString op;
        QStringList argNames;
        QJsonObject args;
        QGraphicsRectItem* box = nullptr;
        QMap<QString, QGraphicsEllipseItem*> inPorts;
        QMap<QString, QGraphicsSimpleTextItem*> argText;
        QGraphicsEllipseItem* outPort = nullptr;
    };
    struct Link {
        int from = 0, to = 0;
        QString arg;
        QGraphicsPathItem* path = nullptr;
    };
    void refreshNode(Node& n);
    void refreshWires();
    void editArgAt(QPointF scenePos);
    int nodeAtOutPort(QPointF p) const;
    bool inPortAt(QPointF p, int* node, QString* arg) const;

    QHash<QString, QStringList> m_ops;
    QMap<int, Node> m_nodes;
    QVector<Link> m_links;
    int m_nextId = 1;
    QGraphicsScene* m_scene = nullptr;
    QGraphicsView* m_view = nullptr;
    QLineEdit* m_name = nullptr;
    QComboBox* m_opBox = nullptr;
    int m_wireFrom = 0;
    QGraphicsPathItem* m_dragWire = nullptr;
};

} // namespace kimbim
