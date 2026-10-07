// Execute the actual UI handler with an isolated DOM and fake API responses.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

async function fixture(response) {
  const nodes = new Map();
  const node = () => ({value:'',textContent:'',disabled:false,children:[],addEventListener(){},
    append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}});
  const document = {getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},createElement:node};
  const context = vm.createContext({document,AbortController,setTimeout,clearTimeout,fetch:async url=>({
    ok:true,status:200,json:async()=>url==='/api/memory/pools'?{pools:[]}:url==='/api/lab/models'?{models:[{name:'fixture'}]}:response
  })});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'world-assets','knowledge-flow.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  vm.runInContext(`packet={text:'Original evidence',citations:[],flow:{stages:[{id:'memory',label:'Memory',status:'ready',tooltip:'Fixture'}]}};
    prepared={query:'Fixture task',pool:'all'};answer='Original answer';globalThis.originalPacket=packet;
    el('evidence').textContent=packet.text;el('answer').textContent=answer;el('model').value='fixture';showFlow(packet.flow);`,context);
  const oldFlow = nodes.get('flow').children;
  await nodes.get('generate').onclick();
  return {context,nodes,oldFlow};
}

test('malformed generated packets preserve prior evidence, answer and flow',async()=>{
  for(const packet of [null,[],{}, {text:'bad',flow:{stages:[]}},
    {text:'bad',citations:[],flow:{stages:[null]}},
    {text:'bad',citations:[],flow:{stages:[{id:'memory',label:'Memory',status:null,tooltip:'Fixture'}]}}]) {
    const {context,nodes,oldFlow}=await fixture({text:'New answer',context_packet:packet});
    assert.equal(vm.runInContext('packet===originalPacket',context),true);
    assert.equal(nodes.get('evidence').textContent,'Original evidence');
    assert.equal(nodes.get('answer').textContent,'Original answer');
    assert.equal(vm.runInContext('answer',context),'Original answer');
    assert.equal(nodes.get('flow').children,oldFlow);
    assert.match(nodes.get('status').textContent,/unusable context packet/);
    assert.equal(vm.runInContext('busy',context),false);
  }
});

test('valid generated packet updates all response surfaces together',async()=>{
  const next={text:'New evidence',citations:[],flow:{stages:[{id:'answer',label:'Answer',status:'ready',tooltip:'Fixture'}]}};
  const {context,nodes,oldFlow}=await fixture({text:'New answer',context_packet:next});
  assert.equal(nodes.get('evidence').textContent,'New evidence');
  assert.equal(nodes.get('answer').textContent,'New answer');
  assert.notEqual(nodes.get('flow').children,oldFlow);
  assert.equal(vm.runInContext('answer',context),'New answer');
  assert.match(nodes.get('status').textContent,/draft ready/);
});
