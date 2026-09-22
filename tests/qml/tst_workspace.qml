import QtQuick
import QtQuick.Controls
import QtTest
import "../.." as Plugin

Item {
  id: host
  width: 960; height: 850
  QtObject {
    id: localService
    property string verifiedAccount: "alice"
    property var localDrafts: ({})
    property var localPositions: ({})
    property var saved: []
    signal localStateLoaded()
    function saveLocal(name,key,value) { saved = saved.concat([{name:name,key:key,value:value}]) }
    function refresh() {}
  }
  Component { id: readerComponent; Plugin.Reader { anchors.fill: parent; service: localService } }
  Plugin.ActionsDialog { id: dialog; parent: host }
  TestCase {
    name: "NativeWorkspace"
    when: windowShown
    property var reader
    SignalSpy { id: submissions; target: dialog; signalName: "submitted" }
    function init() {
      localService.saved=[];localService.localDrafts=({});localService.localPositions=({})
      reader=createTemporaryObject(readerComponent,host)
      reader.item={kind:"collection",repo:"",collection:"repositories"}
      reader.detail={target:reader.item,title:"Repositories",subtitle:"GitHub",body:"",canReply:false,warnings:[],threadId:"",actions:[],
        tabs:[{id:"collection",label:"Repositories",blocks:[{title:"example/one",body:"A repository",action:{kind:"repository",repo:"example/one"},operationLabel:"Open repository"}]}],
        nextTarget:{kind:"collection",repo:"",collection:"repositories",page:2},pageLabel:"Page 1 · 30 items"}
      reader.focusReader();dialog.sending=false;dialog.close();submissions.clear();wait(20)
    }
    function cleanup() { dialog.sending=false;dialog.close() }
    function control(label) { var a=[];reader.keyboardControls(reader,a);for(var i=0;i<a.length;i++) if(a[i].text===label)return a[i];return null }
    function test_repository_drilldown_and_next_page_are_native_targets() {
      control("Next page").clicked()
      compare(reader.item.page,2);compare(reader.item.kind,"collection")
      compare(reader.history.length,1)
    }
    function test_find_input_keeps_keyboard_letters_and_selects_log_matches() {
      reader.detail=Object.assign({},reader.detail,{tabs:[{id:"logs",label:"Logs",blocks:[{title:"Job",body:"first\nerror running\nlast",action:null}]}]})
      reader.tabId="logs";wait(20)
      var input=findChild(reader,"readerFind");verify(input)
      input.forceActiveFocus();keyClick(Qt.Key_R);keyClick(Qt.Key_A);keyClick(Qt.Key_N)
      compare(input.text,"ran");verify(!reader.actionOpen);verify(!reader.busy)
      input.text="error";keyClick(Qt.Key_Return)
      compare(reader.selectedBlock,0);compare(reader.findOffset,11)
    }
    function test_reply_draft_is_sent_to_durable_local_state() {
      reader.item={kind:"issue",repo:"a/b",number:1}
      reader.detail=Object.assign({},reader.detail,{target:reader.item,canReply:true})
      reader.startReply();wait(10)
      keyClick(Qt.Key_H);keyClick(Qt.Key_I)
      reader.saveDraft()
      verify(localService.saved.length>0)
      var last=localService.saved[localService.saved.length-1]
      compare(last.name,"drafts");compare(last.value,"hi")
    }
    function test_cached_details_have_no_remote_action_menu() {
      reader.detail=Object.assign({},reader.detail,{cached:true})
      reader.openActions();verify(!reader.actionOpen)
      compare(control("Actions… (A)"), null)
    }
    function test_local_filter_applies_without_a_remote_write_confirmation() {
      dialog.prepare(reader.detail,[{id:"browse-filter",label:"Filter",description:"Show repos",fields:[{key:"owner",label:"Owner",value:"alice"}],expected:{}}])
      dialog.choose(0);wait(20)
      dialog.review()
      compare(submissions.count,1)
      compare(submissions.signalArguments[0][0].action,"browse-filter")
      compare(submissions.signalArguments[0][0].values.owner,"alice")
    }
    function test_remote_publication_still_requires_separate_confirmation() {
      dialog.prepare({target:{kind:"release",repo:"a/b",number:3},title:"v1"},[{id:"publish-release",label:"Publish release",description:"Publish v1",fields:[],expected:{release:3}}])
      dialog.choose(0);wait(20)
      compare(submissions.count,0)
      keyClick(Qt.Key_Return);compare(submissions.count,0)
    }
  }
}
