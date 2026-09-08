import QtQuick
import QtTest
import "../.." as Plugin
Item {
  width: 1180; height: 760
  QtObject {
    id: fakeService
    property var notifications: [{id:"n1",title:"First",repo:"test/repo",kind:"issue",number:1},{id:"n2",title:"Second",repo:"test/repo",kind:"issue",number:2}]
    property var issues: notifications
    property var pullRequests: notifications
    property var discussions: []
    property var ci: []
    property var searchResults: []
    property var searchFilters: ({})
    property int searchPage: 0
    property int searchTotal: 0
    property bool searchMore: false
    property bool searching: false
    property string searchError: ""
    property string searchWarning: ""
    function search(filters, append) { searchFilters = filters; searchResults = notifications; searchPage = 1; searchTotal = 2 }

    property int reviewRequestCount: 0
    property int failingCiCount: 0
    property string viewer: "test"
    property string lastError: ""
    property string errorKind: ""
    property bool partial: false
    property bool refreshing: false
    property int attentionCount: 2
    function refresh() {}
  }
  Component { id: panelComponent; Plugin.Panel { service: fakeService } }
  TestCase {
    name: "DashboardDrilldown"
    when: windowShown
    property var panel
    function init() { panel=createTemporaryObject(panelComponent,parent); verify(panel); panel.open("{}"); wait(30) }
    function state() { return JSON.parse(panel.navigationState()) }
    function test_sections_items_reader_back() {
      compare(state().area,"sections")
      keyClick(Qt.Key_Down)
      compare(state().section,1)
      compare(state().area,"sections")
      keyClick(Qt.Key_Right)
      compare(state().area,"items")
      keyClick(Qt.Key_Down)
      compare(state().item,1)
      keyClick(Qt.Key_Backspace)
      compare(state().area,"sections")
      keyClick(Qt.Key_Return)
      compare(state().item,1)
      compare(state().area,"items")
      keyClick(Qt.Key_Right)
      verify(state().readerOpen)
      keyClick(Qt.Key_Left)
      verify(!state().readerOpen)
      compare(state().item,1)
      compare(state().area,"items")
      keyClick(Qt.Key_Left)
      compare(state().area,"sections")
    }
    function test_search_typing_results_and_reader_back() {
      keyClick(Qt.Key_Slash); wait(20)
      compare(state().section,5);verify(state().searchFocused)
      keyClick(Qt.Key_R);keyClick(Qt.Key_N);keyClick(Qt.Key_1)
      compare(state().section,5);verify(!state().readerOpen)
      keyClick(Qt.Key_Return);wait(20)
      compare(fakeService.searchFilters.query,"rn1")
      compare(state().searchCount,2);compare(state().area,"items");verify(!state().searchFocused)
      keyClick(Qt.Key_Down);compare(state().item,1)
      keyClick(Qt.Key_Right);verify(state().readerOpen)
      keyClick(Qt.Key_Left);verify(!state().readerOpen)
      compare(state().section,5);compare(state().item,1)
      keyClick(Qt.Key_Slash);wait(20);verify(state().searchFocused)
      keyClick(Qt.Key_Escape);compare(state().area,"items");verify(!state().searchFocused)
    }
    function test_sections_stop_at_ends() {
      keyClick(Qt.Key_Up)
      compare(state().section,0)
      keyClick(Qt.Key_End)
      compare(state().section,5)
      keyClick(Qt.Key_Down)
      compare(state().section,5)
    }
  }
}
