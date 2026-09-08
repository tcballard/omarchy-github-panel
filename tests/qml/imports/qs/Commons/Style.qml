pragma Singleton
import QtQuick
QtObject {
  property var font: ({family:"monospace",caption:12,body:14,subtitle:18,iconLarge:20,icon:16})
  property int cornerRadius: 3
  function space(n) { return n }
  function pressedFillFor(a,b) { return "#444444" }
  function selectedFillFor(a,b) { return "#333333" }
  function hoverFillFor(a,b) { return "#222222" }
}
