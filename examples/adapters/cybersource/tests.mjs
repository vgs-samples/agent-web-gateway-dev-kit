import assert from 'node:assert/strict';
import vm from 'node:vm';
import {test,har,fixture,context,relay,hash,decrypt} from '../testing/harness.mjs';
export async function run(){
 const page=fixture((await har('cybersource','capture'))[0],'response');
 page.body=page.body.replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.synthetic/,context);
 let captured;
 await test('cybersource','capture','capture.star',page,{verify:r=>{assert.equal(r.body,page.body);assert.equal(r.values.cybersource_capture_context,context);assert.deepEqual(r.reveals,[]);captured=r.values;}});
 await test('cybersource','capture-unrelated','capture.star',{...page,body:'{"hello":"world"}'},{verify:r=>assert.deepEqual(r.values,{})});
 await test('cybersource','ambiguous-context','capture.star',{...page,body:context+' '+context.replace('.synthetic','.other')},{error:'CS_CAPTURE_AMBIGUOUS'});
 const aliases={number:'4242424242424242',securityCode:'999'};
 const settings={cybersource_number_standin:aliases.number,cybersource_cvc_standin:aliases.securityCode};
 const sdk={...fixture((await har('cybersource','bridge-sdk'))[0],'response'),context:settings};sdk.inputs={sdk_sha256:hash(sdk.body)};
 let patched;
 await test('cybersource','sdk-bridge','bridge-sdk.star',sdk,{verify:r=>{assert(r.body.includes('AWGCS1:'));assert(r.headers.some(([k,v])=>k==='Cache-Control'&&v==='no-store, private'));assert.deepEqual(r.reveals,[]);patched=r.body;}});
 await test('cybersource','sdk-version-guard','bridge-sdk.star',{...sdk,body:sdk.body+' '},{error:'CS_SDK_VERSION_MISMATCH'});
 await test('cybersource','sdk-alias-guard','bridge-sdk.star',{...sdk,context:{}},{error:'CS_STANDINS_MISSING'});
 // Exercise only our authored SDK double and injected bridge, never captured JS.
 if(patched){
  const scope={TextEncoder};vm.createContext(scope);vm.runInContext(patched,scope);
  assert.match(await scope.je({CARD:aliases},{raw:context},0),/^AWGCS1:[a-p]+$/);
  assert.equal(await scope.je({CARD:{number:'4111111111111111'}},{raw:context},0),'ORIGINAL_PROVIDER_PATH');
 }
 const token=fixture((await har('cybersource','encrypt'))[0]);
 assert.match(token.body,/^AWGCS1:(?:[a-p]{2})+$/);
 const encoded=token.body.slice('AWGCS1:'.length);
 const bytes=[];
 for(let i=0;i<encoded.length;i+=2)bytes.push(((encoded.charCodeAt(i)-97)<<4)|(encoded.charCodeAt(i+1)-97));
 const envelope=JSON.parse(Buffer.from(bytes).toString('utf8'));
 // Use the test's owned key while retaining the HAR's actual relay payload.
 envelope.context=context;
 const request={...token,context:settings,captured,body:relay(envelope)};
 await test('cybersource','non-relay','encrypt.star',{...request,body:'unchanged'},{verify:r=>{assert.equal(r.body,'unchanged');assert.deepEqual(r.reveals,[]);}});
 await test('cybersource','missing-context','encrypt.star',{...request,captured:{}},{error:'CS_CONTEXT_MISSING'});
 await test('cybersource','context-mismatch','encrypt.star',{...request,body:relay({...envelope,context:context+'.other'})},{error:'CS_CONTEXT_MISMATCH'});
 await test('cybersource','alias-mismatch','encrypt.star',{...request,context:{...settings,cybersource_number_standin:'different'}},{error:'CS_STANDIN_MISMATCH'});
 for(const role of ['both','number','cvc']){
  const payload=structuredClone(envelope);
  if(role==='number')delete payload.data.CARD.securityCode;
  if(role==='cvc')delete payload.data.CARD.number;
  const expected=structuredClone(payload);
  if(role!=='cvc')expected.data.CARD.number='4111111111111111';
  if(role!=='number')expected.data.CARD.securityCode='123';
  await test('cybersource','encrypt-'+role,'encrypt.star',{...request,body:relay(payload)},{crypto:true,verify:r=>{assert.deepEqual(decrypt(r.body,'RSA-OAEP'),expected);assert.equal(r.reveals.length,role==='both'?2:1);}});
 }
}
