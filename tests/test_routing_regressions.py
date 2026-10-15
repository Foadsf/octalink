"""Obstacle routing regressions found while building internet-derived models."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, QRectF, QCoreApplication, QEvent
from PyQt6.QtGui import QPainterPath, QPainterPathStroker
from PyQt6.QtWidgets import QApplication, QGraphicsItem
from octalink_gui import OctaLinkMainWindow, SimCanvasScene, BlockItem

APP = QApplication.instance() or QApplication([])


class RoutingRegressions(unittest.TestCase):
    def setUp(self):
        self.window = OctaLinkMainWindow()
        self.window.new_model()
        self.scene = self.window.root_scene
        self.source = self.scene.add_sim_block("Constant", 50, 200)
        self.sink = self.scene.add_sim_block("Scope", 650, 200)

    def tearDown(self):
        self.window.saved_document = self.window.serialize_model()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def assert_avoids(self, wire, obstacle):
        rect = obstacle.mapRectToScene(obstacle.boundingRect()).adjusted(2, 2, -2, -2)
        # The same intersection instrument must detect a known bad straight line.
        bad = QPainterPath(wire.start_port.scene_pos())
        bad.lineTo(wire.end_port.scene_pos())
        stroke = QPainterPathStroker()
        stroke.setWidth(2)
        self.assertTrue(stroke.createStroke(bad).intersects(rect), "Control does not cross the obstacle")
        good = QPainterPath(wire.start_port.scene_pos())
        good.lineTo(good.currentPosition().x(), rect.top()-30)
        good.lineTo(wire.end_port.scene_pos().x(), rect.top()-30)
        good.lineTo(wire.end_port.scene_pos())
        self.assertFalse(stroke.createStroke(good).intersects(rect), "Known clear control was rejected")
        self.assertFalse(stroke.createStroke(wire.path()).intersects(rect), "Signal route crosses an unrelated block")
        elements = [wire.path().elementAt(i) for i in range(wire.path().elementCount())]
        self.assertTrue(all(a.x == b.x or a.y == b.y for a, b in zip(elements, elements[1:])))
        self.assertEqual(QPointF(elements[0].x, elements[0].y), wire.start_port.scene_pos())
        self.assertEqual(QPointF(elements[-1].x, elements[-1].y), wire.end_port.scene_pos())

    def test_new_wire_avoids_existing_block_before_wire_has_scene(self):
        obstacle = self.scene.add_sim_block("Gain", 330, 200)
        wire = self.scene.connect_ports(self.source.out_ports[0], self.sink.in_ports[0])
        self.assert_avoids(wire, obstacle)
        # A close forward-facing destination must stay a short forward route,
        # rather than becoming a feedback detour when endpoint stubs overlap.
        self.scene.remove_wire(wire)
        self.sink.setPos(158, 200)
        wire = self.scene.connect_ports(self.source.out_ports[0], self.sink.in_ports[0])
        expected = wire.end_port.scene_pos().x()-wire.start_port.scene_pos().x()
        self.assertAlmostEqual(wire.path().length(), expected)
        bad = QPainterPath(wire.start_port.scene_pos())
        bad.lineTo(160, 230)
        bad.lineTo(160, 305)
        bad.lineTo(136, 305)
        bad.lineTo(136, 230)
        bad.lineTo(wire.end_port.scene_pos())
        self.assertGreater(bad.length(), expected+100)

    def test_unconnected_obstacle_move_reroutes_existing_signal(self):
        obstacle = self.scene.add_sim_block("Gain", 330, 450)
        wire = self.scene.connect_ports(self.source.out_ports[0], self.sink.in_ports[0])
        obstacle.setPos(330, 200)
        self.assert_avoids(wire, obstacle)

    def test_internet_models_both_styles_avoid_unrelated_block_bodies(self):
        stroke = QPainterPathStroker()
        stroke.setWidth(1)
        def diagrams(scene):
            # Subsystem interiors are diagrams too (motor, pendulum, heater...).
            yield scene
            for block in scene.blocks:
                if block.block_type == "Subsystem" and block.sub_scene is not None:
                    yield from diagrams(block.sub_scene)

        for model in sorted((Path(__file__).resolve().parents[1]/"examples").glob("mwe_*.json")):
            self.window.load_model_from_file(model)
            for curved, scene in [(c, s) for c in (False, True) for s in diagrams(self.window.root_scene)]:
                scene.connection_style = "curved" if curved else "orthogonal"
                for wire in scene.wires:
                    wire.update_path()
                for wire in scene.wires:
                    if curved:
                        self.assertTrue(any(wire.path().elementAt(i).isCurveTo()
                                            for i in range(wire.path().elementCount())))
                    for block in scene.blocks:
                        if block in (wire.start_port.parent_block, wire.end_port.parent_block):
                            continue
                        with self.subTest(model=model.name, curved=curved, obstacle=block.name,
                                          source=wire.start_port.parent_block.name):
                            rect = QRectF(block.pos().x()+2, block.pos().y()+2, block.width-4, block.height-4)
                            self.assertFalse(stroke.createStroke(wire.path()).intersects(rect))


if __name__ == "__main__":
    if "--mutation-control" in sys.argv:
        # Reproduce the missing obstacle context at initial path construction.
        original = SimCanvasScene.connect_ports
        def missing_scene_context(scene, output, input_port):
            with patch.object(output.parent_block, "scene", return_value=None):
                return original(scene, output, input_port)
        SimCanvasScene.connect_ports = missing_scene_context
        case = "test_new_wire_avoids_existing_block_before_wire_has_scene"
    elif "--movement-control" in sys.argv:
        # Reintroduce the former connected-signals-only position callback.
        def connected_only(block, change, value):
            if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
                for port in block.in_ports + block.out_ports:
                    for wire in port.wires:
                        wire.update_path()
            return QGraphicsItem.itemChange(block, change, value)
        BlockItem.itemChange = connected_only
        case = "test_unconnected_obstacle_move_reroutes_existing_signal"
    elif "--curved-control" in sys.argv:
        import mvp_editor
        class NoObstacleStroke(QPainterPathStroker):
            def createStroke(self, path):
                return QPainterPath()
        # Disable only the router's collision detector; the independent test
        # instrument above retains the real Qt stroke implementation.
        mvp_editor.QPainterPathStroker = NoObstacleStroke
        case = "test_internet_models_both_styles_avoid_unrelated_block_bodies"
    else:
        unittest.main(verbosity=2)
        sys.exit(0)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([RoutingRegressions(case)]))
    print(f"ROUTING MUTATION: {len(result.failures)} crossing failures; {len(result.errors)} errors.")
    sys.exit(0 if result.wasSuccessful() else 1)
