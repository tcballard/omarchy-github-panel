import QtQuick
import QtTest
import "../.." as Plugin

Item {
  width: 760
  height: 800
  Plugin.Reader { id: reader; anchors.fill: parent }
  TestCase {
    name: "GitHubReaderKeyboard"
    when: windowShown
    SignalSpy { id: backSpy; target: reader; signalName: "back" }
    function init() {
      reader.item = {kind: "issue", repo: "test/repo", number: 1}
      reader.detail = {title: "Test thread", subtitle: "test/repo #1", body: "A long thread\n".repeat(120),
        target: reader.item, canReply: true, warnings: [], threadId: "", nextPage: null, nextCursor: null,
        tabs: [{id: "conversation", label: "Conversation", blocks: []}, {id: "reviews", label: "Reviews", blocks: []},
          {id: "changes", label: "Changes", blocks: []}]}
      reader.history = []
      reader.composing = false
      reader.drafts = ({})
      reader.focusReader()
      backSpy.clear()
      wait(30)
    }
    function controls() { var a=[]; reader.keyboardControls(reader,a); return a }
    function named(label) { var a=controls(); for(var i=0;i<a.length;i++) if(a[i].text===label) return a[i]; return null }
    function composer() { var a=controls(); for(var i=0;i<a.length;i++) if(a[i].placeholderText!==undefined) return a[i]; return null }
    function test_diff_and_thread_controls_open_native_action_menu() {
      var d=Object.assign({},reader.detail)
      d.tabs=[{id:"changes",label:"Changes",blocks:[{title:"file.py",body:"L1 R1 context",action:null,operationLabel:"Comment on line…",operations:[
        {id:"inline-comment",label:"Comment on a diff line",description:"file.py",expected:{},fields:[{key:"body",label:"Comment",value:"",required:true,multiline:true}]}]}]}]
      reader.detail=d;reader.tabId="changes";wait(20)
      keyClick(Qt.Key_Down);verify(named("Comment on line…").activeFocus)
      keyClick(Qt.Key_Right);wait(20);verify(reader.actionOpen)
      keyClick(Qt.Key_Return);wait(20);verify(reader.actionOpen)
      keyClick(Qt.Key_Escape);keyClick(Qt.Key_Escape);wait(20)
      verify(!reader.actionOpen);verify(!reader.busy);compare(reader.tabId,"changes")
    }
    function test_tabs_and_keyboard_button_activation() {
      reader.tabId="conversation"
      keyClick(Qt.Key_BracketRight)
      compare(reader.tabId,"reviews")
      verify(named("Reviews").activeFocus)
      keyClick(Qt.Key_BracketRight)
      compare(reader.tabId,"changes")
      keyClick(Qt.Key_BracketLeft)
      compare(reader.tabId,"reviews")
      keyClick(Qt.Key_1)
      compare(reader.tabId,"conversation")
      named("Changes").forceActiveFocus()
      keyClick(Qt.Key_Return)
      compare(reader.tabId,"changes")
    }
    function test_tab_cycle_stays_in_reader() {
      var a=controls()
      reader.focusReader()
      for(var i=0;i<a.length;i++) { keyClick(Qt.Key_Tab); verify(a[i].activeFocus,"focus index "+i) }
      keyClick(Qt.Key_Tab)
      verify(a[0].activeFocus)
      keyClick(Qt.Key_Backtab)
      verify(a[a.length-1].activeFocus)
    }
    function test_reply_typing_escape_and_draft() {
      keyClick(Qt.Key_C)
      verify(reader.composing)
      var edit=composer()
      verify(edit.activeFocus)
      edit.text=""
      keyClick(Qt.Key_R)
      keyClick(Qt.Key_J)
      keyClick(Qt.Key_1)
      keyClick(Qt.Key_Return)
      keyClick(Qt.Key_C)
      compare(edit.text,"rj1\nc")
      verify(!reader.busy)
      keyClick(Qt.Key_Escape)
      verify(!reader.composing)
      compare(backSpy.count,0)
      compare(reader.drafts[reader.draftKey],"rj1\nc")
      keyClick(Qt.Key_C)
      compare(composer().text,"rj1\nc")
      keyClick(Qt.Key_Tab)
      verify(named("Post reply").activeFocus)
      // Do not activate Post reply: this suite never calls the GitHub API.
      keyClick(Qt.Key_Backtab)
      verify(composer().activeFocus)
      keyClick(Qt.Key_Escape)
      keyClick(Qt.Key_Escape)
      compare(backSpy.count,1)
    }
    function test_left_and_backspace_go_back() {
      keyClick(Qt.Key_Left)
      compare(backSpy.count,1)
      keyClick(Qt.Key_Backspace)
      compare(backSpy.count,2)
    }
    function test_reply_left_and_backspace_edit_text() {
      reader.startReply()
      var edit=composer()
      edit.text="abc"
      edit.cursorPosition=3
      keyClick(Qt.Key_Left)
      keyClick(Qt.Key_Backspace)
      compare(edit.text,"ac")
      compare(backSpy.count,0)
      verify(reader.composing)
    }
    function test_actionable_items_use_up_down() {
      reader.detail = {title:"Runs",subtitle:"test/repo",body:"",target:reader.item,canReply:false,warnings:[],threadId:"",
        tabs:[{id:"checks",label:"Runs",blocks:[
          {title:"First run",body:"Passed",action:{kind:"run",repo:"test/repo",number:1}},
          {title:"Second run",body:"Failed",action:{kind:"run",repo:"test/repo",number:2}}]}]}
      reader.selectedBlock=-1
      wait(20)
      keyClick(Qt.Key_Down)
      compare(reader.selectedBlock,0)
      keyClick(Qt.Key_Down)
      compare(reader.selectedBlock,1)
      keyClick(Qt.Key_Up)
      compare(reader.selectedBlock,0)
    }
    function test_scroll_after_text_focus() {
      var scroll=findChild(reader,"readerScroll")
      verify(scroll!==null)
      reader.tabId="conversation"
      wait(20)
      var text=findChild(reader,"threadBody")
      text.forceActiveFocus()
      keyClick(Qt.Key_End)
      verify(scroll.contentItem.contentY>0)
      keyClick(Qt.Key_Home)
      compare(scroll.contentItem.contentY,0)
      keyClick(Qt.Key_J)
      verify(scroll.contentItem.contentY>0)
      keyClick(Qt.Key_BracketRight)
      compare(reader.tabId,"reviews")
    }
  }
}
