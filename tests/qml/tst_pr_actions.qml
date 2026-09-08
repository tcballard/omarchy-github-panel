import QtQuick
import QtTest
import "../.." as Plugin
Item {
  id: host
  width: 700; height: 760
  Plugin.PRActionDialog { id: dialog; parent: host }
  TestCase {
    name: "PRActionConfirmation"
    when: windowShown
    SignalSpy { id: submitted; target: dialog; signalName: "submitted" }
    function snapshot() {
      return {title:"Example PR",target:{kind:"pull-request",repo:"test/repo",number:9},
        pr:{headSha:"a".repeat(40),headRef:"feature",baseRef:"main",mergeState:"clean",mergeMethods:["squash","merge"],
          canReview:true,reviewReason:"",canMerge:true,mergeReason:""}}
    }
    function init() { dialog.sending=false; dialog.close(); submitted.clear(); wait(10) }
    function cleanup() { dialog.sending=false; dialog.close() }
    function test_enter_defaults_to_cancel() {
      dialog.prepare("merge",snapshot());wait(30)
      verify(findChild(dialog,"cancelPRAction").activeFocus)
      keyClick(Qt.Key_Return)
      verify(!dialog.visible)
      compare(submitted.count,0)
    }
    function test_review_note_and_explicit_submit() {
      dialog.prepare("request-changes",snapshot());wait(30)
      verify(!dialog.canSubmit)
      var note=findChild(dialog,"reviewNote")
      note.forceActiveFocus()
      keyClick(Qt.Key_R);keyClick(Qt.Key_Return);keyClick(Qt.Key_C)
      compare(note.text,"r\nc")
      compare(submitted.count,0)
      verify(dialog.canSubmit)
      var confirm=findChild(dialog,"confirmPRAction")
      confirm.forceActiveFocus()
      keyClick(Qt.Key_Return)
      compare(submitted.count,1)
      var request=submitted.signalArguments[0][0]
      compare(request.action,"request-changes")
      compare(request.body,"r\nc")
      compare(request.expectedHeadSha,"a".repeat(40))
      verify(request.confirmed)
      dialog.confirm()
      compare(submitted.count,1)
    }
    function test_snapshot_and_method_are_bound_to_confirmation() {
      var value=snapshot()
      dialog.prepare("merge",value);wait(30)
      value.target.number=10;value.pr.headSha="b".repeat(40)
      dialog.selectedMethod="merge"
      dialog.confirm()
      compare(submitted.count,1)
      var request=submitted.signalArguments[0][0]
      compare(request.item.number,9)
      compare(request.expectedHeadSha,"a".repeat(40))
      compare(request.mergeMethod,"merge")
      dialog.finish("Network error; refresh before retrying.")
      verify(dialog.visible)
      verify(!dialog.canSubmit)
      dialog.confirm()
      compare(submitted.count,1)
    }
    function test_blocked_actions_cannot_submit() {
      var value=snapshot();value.pr.canReview=false;value.pr.reviewReason="Your own PR"
      dialog.prepare("approve",value);wait(20)
      dialog.confirm();compare(submitted.count,0)
      dialog.close()
      value.pr.canMerge=false;value.pr.mergeReason="Required checks pending"
      dialog.prepare("merge",value);wait(20)
      dialog.confirm();compare(submitted.count,0)
    }
  }
}
