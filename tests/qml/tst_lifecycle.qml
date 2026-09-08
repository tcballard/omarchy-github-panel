import QtQuick
import QtTest
import "../.." as Plugin
Item {
  id: host
  width: 700; height: 760
  Plugin.ActionsDialog { id: dialog; parent: host }
  TestCase {
    name: "LifecycleActions"
    when: windowShown
    SignalSpy { id: submitted; target: dialog; signalName: "submitted" }
    function visualChild(parent, name) {
      if (parent.objectName === name) return parent
      var children=parent.children || []
      for (var i=0;i<children.length;i++) { var found=visualChild(children[i],name);if(found) return found }
      return null
    }
    function choices() { return [
      {id:"close",label:"Close issue",description:"Close it",expected:{state:"open"},fields:[]},
      {id:"edit-issue",label:"Edit issue",description:"Save changes",expected:{state:"open"},fields:[
        {key:"title",label:"Title",value:"Old title",required:true},
        {key:"body",label:"Description",value:"",multiline:true}]},
      {id:"auto-merge",label:"Enable auto-merge",description:"When ready",expected:{},reason:"Not allowed",fields:[]}
    ] }
    function init() {
      dialog.sending=false; dialog.close(); submitted.clear()
      dialog.prepare({title:"Example",target:{repo:"a/b",kind:"issue",number:9}},choices()); wait(30)
    }
    function cleanup() { dialog.sending=false;dialog.close() }
    function test_drilldown_and_back_never_submit() {
      var menu=findChild(dialog,"actionMenu")
      verify(menu.activeFocus)
      keyClick(Qt.Key_Down); compare(menu.currentIndex,1)
      keyClick(Qt.Key_Right); compare(dialog.stage,1)
      wait(20)
      verify(visualChild(dialog.contentItem,"field_title").activeFocus)
      keyClick(Qt.Key_Escape);compare(dialog.stage,0)
      keyClick(Qt.Key_Up);keyClick(Qt.Key_Return);compare(dialog.stage,2)
      // Opening a confirmation focuses Back, so an extra Enter does not write.
      wait(20);keyClick(Qt.Key_Return);compare(dialog.stage,0)
      compare(submitted.count,0)
      keyClick(Qt.Key_Left);verify(!dialog.visible)
    }
    function test_form_editing_review_then_explicit_confirmation() {
      keyClick(Qt.Key_Down);keyClick(Qt.Key_Return);wait(20)
      compare(dialog.stage,1)
      compare(dialog.selected.id,"edit-issue")
      var body=visualChild(dialog.contentItem,"field_body")
      verify(body !== null, "Body field exists")
      body.forceActiveFocus();keyClick(Qt.Key_A);keyClick(Qt.Key_Return);keyClick(Qt.Key_B)
      keyClick(Qt.Key_Left);keyClick(Qt.Key_Backspace)
      compare(dialog.stage,1);compare(submitted.count,0)
      compare(dialog.values.body,"ab")
      var primary=findChild(dialog,"actionConfirm")
      primary.forceActiveFocus();keyClick(Qt.Key_Return);wait(20)
      compare(dialog.stage,2);compare(submitted.count,0)
      verify(findChild(dialog,"actionBack").activeFocus)
      keyClick(Qt.Key_Down);verify(primary.activeFocus)
      keyClick(Qt.Key_Return);compare(submitted.count,1)
      var req=submitted.signalArguments[0][0]
      compare(req.values.body,"ab");compare(req.item.number,9);verify(req.confirmed)
      dialog.confirm();compare(submitted.count,1)
      keyClick(Qt.Key_Left);verify(dialog.visible);compare(dialog.stage,2)
      dialog.finish("Network error. Refresh first.")
      verify(!dialog.valid);dialog.confirm();compare(submitted.count,1)
      findChild(dialog,"actionBack").forceActiveFocus();keyClick(Qt.Key_Return);verify(!dialog.visible)
    }
    function test_snapshot_is_immutable_and_blocked_action_explains_reason() {
      var data={target:{repo:"a/b",kind:"issue",number:9}}
      var entries=choices()
      dialog.prepare(data,entries);wait(20)
      data.target.number=10;entries[0].expected.state="closed"
      keyClick(Qt.Key_Return);wait(20)
      dialog.confirm();compare(submitted.count,1)
      var req=submitted.signalArguments[0][0]
      compare(req.item.number,9);compare(req.expected.state,"open")
      dialog.finish("");dialog.prepare(data,entries);wait(20)
      keyClick(Qt.Key_Down);keyClick(Qt.Key_Down);keyClick(Qt.Key_Right);wait(20)
      compare(dialog.selected.reason,"Not allowed");verify(!dialog.valid)
      dialog.confirm();compare(submitted.count,1)
    }
    function test_required_fields_and_method_selection() {
      dialog.prepare({target:{repo:"a/b"}},[{id:"auto-merge",label:"Auto-merge",description:"Merge later",expected:{},fields:[
        {key:"mergeMethod",label:"Method",value:"squash",options:["squash","merge"],required:true}]}]);wait(20)
      keyClick(Qt.Key_Right);wait(20);verify(dialog.valid)
      dialog.setValue("mergeMethod","admin");verify(!dialog.valid)
      dialog.setValue("mergeMethod","merge");dialog.review();dialog.confirm()
      compare(submitted.count,1);compare(submitted.signalArguments[0][0].values.mergeMethod,"merge")
    }
  }
}
