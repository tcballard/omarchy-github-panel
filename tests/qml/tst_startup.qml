import QtQuick
import QtTest
import "../.." as Plugin
Item {
  width: 1180; height: 760
  QtObject {
    id: fakeService
    property var notifications: []
    property var issues: []
    property var pullRequests: []
    property var discussions: []
    property var ci: []
    property var searchResults: []
    property string lastError: ""
    function refresh() {}
  }
  Component { id: panelComponent; Plugin.Panel { service: fakeService } }
  TestCase {
    name: "PanelStartup"
    when: windowShown
    function panelWindow(panel) {
      for (var i = 0; i < panel.children.length; i++)
        if (panel.children[i].title === "Omarchy GitHub") return panel.children[i]
      return null
    }
    // keepLoaded makes the shell create the panel at startup; it must stay
    // hidden until the host opens it.
    function test_window_hidden_until_opened() {
      var panel=createTemporaryObject(panelComponent,parent);verify(panel)
      var window=panelWindow(panel);verify(window)
      verify(!window.visible);verify(!panel.opened)
      panel.open("{}");wait(30)
      verify(window.visible)
      panel.close()
      verify(!window.visible)
    }
  }
}
