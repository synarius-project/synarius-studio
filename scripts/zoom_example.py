from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent, QPainter, QColor, QPen

class ZoomView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event: QWheelEvent):
        # Fixpunkt auf Mauszeiger setzen
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        zoom_factor = 1.15
        if event.angleDelta().y() < 0:
            zoom_factor = 1 / zoom_factor

        self.scale(zoom_factor, zoom_factor)

if __name__ == "__main__":
    app = QApplication([])
    scene = QGraphicsScene()
    
    # Raster zeichnen
    pen = QPen(QColor("lightgray"))
    for i in range(0, 505, 50):
        scene.addLine(i, 0, i, 500, pen)
        scene.addLine(0, i, 500, i, pen)
    
    # Die korrigierte Zeile:
    scene.addEllipse(225, 225, 50, 50, brush=QColor("red"))
    
    view = ZoomView(scene)
    view.resize(800, 600)
    view.show()
    app.exec()