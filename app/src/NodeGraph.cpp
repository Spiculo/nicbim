// SPDX-License-Identifier: GPL-3.0-or-later
#include "NodeGraph.h"

#include <QBrush>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QGraphicsPathItem>
#include <QGraphicsScene>
#include <QGraphicsSceneMouseEvent>
#include <QGraphicsSimpleTextItem>
#include <QGraphicsView>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QJsonDocument>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPainterPath>
#include <QPen>
#include <QPushButton>
#include <QVBoxLayout>

namespace kimbim {

namespace {

constexpr double kWidth = 180.0;
constexpr double kTitle = 22.0;
constexpr double kRow = 20.0;
constexpr double kPort = 10.0;

// A node box that tells the dialog when it moved, so the wires follow.
class NodeBox : public QGraphicsRectItem {
public:
    NodeBox(const QRectF& r, std::function<void()> moved)
        : QGraphicsRectItem(r)
        , m_moved(std::move(moved))
    {
        setFlags(ItemIsMovable | ItemIsSelectable | ItemSendsGeometryChanges);
    }

protected:
    QVariant itemChange(GraphicsItemChange change, const QVariant& value) override
    {
        if (change == ItemPositionHasChanged && m_moved)
            m_moved();
        return QGraphicsRectItem::itemChange(change, value);
    }

private:
    std::function<void()> m_moved;
};

QString valueText(const QJsonValue& v)
{
    if (v.isDouble())
        return QString::number(v.toDouble(), 'g', 10);
    if (v.isString())
        return v.toString();
    if (v.isUndefined() || v.isNull())
        return QStringLiteral("-");
    return QString::fromUtf8(QJsonDocument(v.isArray() ? QJsonDocument(v.toArray()) : QJsonDocument(v.toObject())).toJson(QJsonDocument::Compact));
}

QPainterPath wirePath(QPointF a, QPointF b)
{
    QPainterPath p(a);
    const double dx = std::max(40.0, std::abs(b.x() - a.x()) / 2);
    p.cubicTo(a + QPointF(dx, 0), b - QPointF(dx, 0), b);
    return p;
}

} // namespace

NodeGraphDialog::NodeGraphDialog(const QJsonArray& ops, const QString& name, const QJsonObject& graph, QWidget* parent)
    : QDialog(parent)
{
    setObjectName(QStringLiteral("nodeGraphDialog"));
    setWindowTitle(tr("Visual script graph"));
    resize(980, 600);
    for (const auto& v : ops) {
        QStringList args;
        for (const auto& a : v.toObject().value("args").toArray())
            args << a.toString();
        m_ops.insert(v.toObject().value("op").toString(), args);
    }
    auto* layout = new QVBoxLayout(this);
    auto* top = new QHBoxLayout;
    top->addWidget(new QLabel(tr("Script:"), this));
    m_name = new QLineEdit(name, this);
    m_name->setObjectName(QStringLiteral("nodeGraphName"));
    top->addWidget(m_name, 1);
    m_opBox = new QComboBox(this);
    m_opBox->addItems(m_ops.keys());
    top->addWidget(m_opBox);
    auto* add = new QPushButton(tr("Add node"), this);
    top->addWidget(add);
    layout->addLayout(top);
    m_scene = new QGraphicsScene(this);
    m_scene->setSceneRect(-200, -200, 3000, 2000);
    m_view = new QGraphicsView(m_scene, this);
    m_view->setRenderHint(QPainter::Antialiasing);
    m_view->setDragMode(QGraphicsView::RubberBandDrag);
    m_scene->installEventFilter(this);
    layout->addWidget(m_view, 1);
    layout->addWidget(new QLabel(tr("Drag from a node's output (right) to another's input (left) to wire them; double-click "
                                    "an input to type its value; Delete removes the selected nodes."),
        this));
    auto* buttons = new QDialogButtonBox(this);
    QPushButton* save = buttons->addButton(tr("Save"), QDialogButtonBox::ActionRole);
    QPushButton* run = buttons->addButton(tr("Save and run"), QDialogButtonBox::ActionRole);
    buttons->addButton(QDialogButtonBox::Close);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(add, &QPushButton::clicked, this, [this] {
        const QPointF centre = m_view->mapToScene(m_view->viewport()->rect().center());
        addNode(m_opBox->currentText(), centre + QPointF(20.0 * (m_nextId % 5), 20.0 * (m_nextId % 5)));
    });
    auto doSave = [this]() -> bool {
        if (!onSave)
            return true;
        const QString error = onSave(this->name(), this->graph());
        if (!error.isEmpty())
            QMessageBox::warning(this, tr("Visual script"), error);
        return error.isEmpty();
    };
    connect(save, &QPushButton::clicked, this, doSave);
    connect(run, &QPushButton::clicked, this, [this, doSave] {
        if (!doSave() || !onRun)
            return;
        const QString error = onRun(this->name());
        if (!error.isEmpty())
            QMessageBox::warning(this, tr("Visual script"), error);
    });

    // the graph to edit
    QHash<int, int> ids; // stored id -> id here
    for (const auto& v : graph.value("nodes").toArray()) {
        const QJsonObject n = v.toObject();
        const int id = addNode(n.value("op").toString(), QPointF(n.value("x").toDouble(), n.value("y").toDouble()),
            n.value("args").toObject());
        if (id)
            ids.insert(n.value("id").toInt(), id);
    }
    for (const auto& v : graph.value("links").toArray()) {
        const QJsonObject l = v.toObject();
        link(ids.value(l.value("from").toInt()), ids.value(l.value("to").toInt()), l.value("arg").toString());
    }
}

int NodeGraphDialog::addNode(const QString& op, QPointF pos, const QJsonObject& args)
{
    if (!m_ops.contains(op))
        return 0;
    Node n;
    n.id = m_nextId++;
    n.op = op;
    n.argNames = m_ops.value(op);
    n.args = args;
    const double h = kTitle + kRow * std::max<qsizetype>(1, n.argNames.size()) + 6;
    const int id = n.id;
    n.box = new NodeBox(QRectF(0, 0, kWidth, h), [this] { refreshWires(); });
    n.box->setBrush(QColor(245, 245, 240));
    n.box->setPen(QPen(QColor(90, 90, 90), 1.2));
    n.box->setPos(pos);
    n.box->setData(0, id);
    m_scene->addItem(n.box);
    auto* title = new QGraphicsSimpleTextItem(QStringLiteral("%1  #%2").arg(op).arg(id), n.box);
    title->setPos(8, 3);
    QFont f = title->font();
    f.setBold(true);
    title->setFont(f);
    for (int i = 0; i < n.argNames.size(); ++i) {
        const double y = kTitle + kRow * i + kRow / 2;
        auto* port = new QGraphicsEllipseItem(-kPort / 2, y - kPort / 2, kPort, kPort, n.box);
        port->setBrush(QColor(70, 130, 200));
        n.inPorts.insert(n.argNames.at(i), port);
        auto* text = new QGraphicsSimpleTextItem(n.box);
        text->setPos(10, y - 8);
        n.argText.insert(n.argNames.at(i), text);
    }
    n.outPort = new QGraphicsEllipseItem(kWidth - kPort / 2, kTitle / 2 - kPort / 2, kPort, kPort, n.box);
    n.outPort->setBrush(QColor(220, 120, 40));
    m_nodes.insert(id, n);
    refreshNode(m_nodes[id]);
    return id;
}

void NodeGraphDialog::refreshNode(Node& n)
{
    for (const QString& arg : n.argNames) {
        QString shown = valueText(n.args.value(arg));
        for (const Link& l : std::as_const(m_links))
            if (l.to == n.id && l.arg == arg)
                shown = QStringLiteral("← #%1").arg(l.from);
        n.argText.value(arg)->setText(QStringLiteral("%1: %2").arg(arg, shown));
    }
}

bool NodeGraphDialog::link(int from, int to, const QString& arg)
{
    if (from == to || !m_nodes.contains(from) || !m_nodes.contains(to) || !m_nodes[to].argNames.contains(arg))
        return false;
    unlink(to, arg); // one wire per input
    Link l{from, to, arg, m_scene->addPath(QPainterPath(), QPen(QColor(220, 120, 40), 2))};
    l.path->setZValue(-1);
    m_links.push_back(l);
    m_nodes[to].args.remove(arg);
    refreshNode(m_nodes[to]);
    refreshWires();
    return true;
}

void NodeGraphDialog::unlink(int to, const QString& arg)
{
    for (int i = int(m_links.size()) - 1; i >= 0; --i)
        if (m_links[i].to == to && m_links[i].arg == arg) {
            delete m_links[i].path;
            m_links.remove(i);
        }
    if (m_nodes.contains(to))
        refreshNode(m_nodes[to]);
}

void NodeGraphDialog::removeNode(int id)
{
    if (!m_nodes.contains(id))
        return;
    for (int i = int(m_links.size()) - 1; i >= 0; --i)
        if (m_links[i].from == id || m_links[i].to == id) {
            const int to = m_links[i].to;
            delete m_links[i].path;
            m_links.remove(i);
            if (to != id && m_nodes.contains(to))
                refreshNode(m_nodes[to]);
        }
    delete m_nodes[id].box;
    m_nodes.remove(id);
}

void NodeGraphDialog::setArg(int node, const QString& arg, const QJsonValue& value)
{
    if (!m_nodes.contains(node))
        return;
    unlink(node, arg);
    m_nodes[node].args.insert(arg, value);
    refreshNode(m_nodes[node]);
}

void NodeGraphDialog::refreshWires()
{
    for (Link& l : m_links) {
        const Node& a = m_nodes[l.from];
        const Node& b = m_nodes[l.to];
        const QPointF from = a.outPort->sceneBoundingRect().center();
        const QPointF to = b.inPorts.value(l.arg)->sceneBoundingRect().center();
        l.path->setPath(wirePath(from, to));
    }
}

QJsonObject NodeGraphDialog::graph() const
{
    QJsonArray nodes, links;
    for (const Node& n : m_nodes)
        nodes.append(QJsonObject{{"id", n.id}, {"op", n.op}, {"args", n.args}, {"x", n.box->pos().x()}, {"y", n.box->pos().y()}});
    for (const Link& l : m_links)
        links.append(QJsonObject{{"from", l.from}, {"to", l.to}, {"arg", l.arg}});
    return QJsonObject{{"nodes", nodes}, {"links", links}};
}

QString NodeGraphDialog::name() const
{
    return m_name->text().trimmed();
}

int NodeGraphDialog::nodeAtOutPort(QPointF p) const
{
    for (const Node& n : m_nodes)
        if (n.outPort->sceneBoundingRect().adjusted(-4, -4, 4, 4).contains(p))
            return n.id;
    return 0;
}

bool NodeGraphDialog::inPortAt(QPointF p, int* node, QString* arg) const
{
    for (const Node& n : m_nodes)
        for (auto it = n.inPorts.constBegin(); it != n.inPorts.constEnd(); ++it)
            if (it.value()->sceneBoundingRect().adjusted(-4, -4, 4, 4).contains(p)) {
                *node = n.id;
                *arg = it.key();
                return true;
            }
    return false;
}

bool NodeGraphDialog::startWire(QPointF scenePos)
{
    m_wireFrom = nodeAtOutPort(scenePos);
    if (!m_wireFrom)
        return false;
    m_dragWire = m_scene->addPath(QPainterPath(), QPen(QColor(220, 120, 40), 2, Qt::DashLine));
    return true;
}

bool NodeGraphDialog::finishWire(QPointF scenePos)
{
    delete m_dragWire;
    m_dragWire = nullptr;
    const int from = std::exchange(m_wireFrom, 0);
    int to = 0;
    QString arg;
    return from && inPortAt(scenePos, &to, &arg) && link(from, to, arg);
}

void NodeGraphDialog::editArgAt(QPointF scenePos)
{
    for (const Node& n : std::as_const(m_nodes))
        for (auto it = n.argText.constBegin(); it != n.argText.constEnd(); ++it)
            if (it.value()->sceneBoundingRect().adjusted(-12, -4, 60, 4).contains(scenePos)) {
                bool ok = false;
                const QString text = QInputDialog::getText(this, tr("Input value"), it.key() + QLatin1Char(':'),
                    QLineEdit::Normal, valueText(n.args.value(it.key())), &ok);
                if (!ok)
                    return;
                bool number = false;
                const double v = text.toDouble(&number);
                setArg(n.id, it.key(), number ? QJsonValue(v) : QJsonValue(text));
                return;
            }
}

bool NodeGraphDialog::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == m_scene) {
        switch (event->type()) {
        case QEvent::GraphicsSceneMousePress: {
            auto* e = static_cast<QGraphicsSceneMouseEvent*>(event);
            if (e->button() == Qt::LeftButton && startWire(e->scenePos()))
                return true;
            break;
        }
        case QEvent::GraphicsSceneMouseMove: {
            auto* e = static_cast<QGraphicsSceneMouseEvent*>(event);
            if (m_dragWire && m_nodes.contains(m_wireFrom)) {
                m_dragWire->setPath(wirePath(m_nodes[m_wireFrom].outPort->sceneBoundingRect().center(), e->scenePos()));
                return true;
            }
            break;
        }
        case QEvent::GraphicsSceneMouseRelease: {
            auto* e = static_cast<QGraphicsSceneMouseEvent*>(event);
            if (m_dragWire) {
                finishWire(e->scenePos());
                return true;
            }
            break;
        }
        case QEvent::GraphicsSceneMouseDoubleClick:
            editArgAt(static_cast<QGraphicsSceneMouseEvent*>(event)->scenePos());
            return true;
        case QEvent::KeyPress:
            if (static_cast<QKeyEvent*>(event)->key() == Qt::Key_Delete) {
                for (QGraphicsItem* item : m_scene->selectedItems())
                    removeNode(item->data(0).toInt());
                return true;
            }
            break;
        default:
            break;
        }
    }
    return QDialog::eventFilter(watched, event);
}

} // namespace kimbim
