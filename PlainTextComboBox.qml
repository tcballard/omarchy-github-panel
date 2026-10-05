import QtQuick
import QtQuick.Controls

// Repository metadata is display text, never rich text (including the popup).
ComboBox {
  id: control
  contentItem: Text {
    text: control.displayText
    textFormat: Text.PlainText
    font: control.font
    color: control.palette.buttonText
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
    leftPadding: control.mirrored && control.indicator ? control.indicator.width + control.spacing : 0
    rightPadding: !control.mirrored && control.indicator ? control.indicator.width + control.spacing : 0
  }
  delegate: ItemDelegate {
    id: option
    required property int index
    width: control.width
    text: control.textAt(index)
    font: control.font
    highlighted: control.highlightedIndex === index
    hoverEnabled: control.hoverEnabled
    contentItem: Text {
      text: option.text
      textFormat: Text.PlainText
      font: option.font
      color: option.palette.text
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
    }
  }
}
