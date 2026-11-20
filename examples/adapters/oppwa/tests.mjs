import assert from 'node:assert/strict';
import {test,har,fixture} from '../testing/harness.mjs';
export async function run(){
 const entries=await har('oppwa','reveal');
 for(const [i,expected,reveals] of [[0,'card.number=4111111111111111',['4242424242424242']],[1,'card.cvv=123',['999']],[2,entries[2].request.postData.text,[]]])
  await test('oppwa','har-entry-'+i,'reveal.star',fixture(entries[i]),{verify:r=>{assert.equal(r.body,expected);assert.deepEqual(r.reveals,reveals);}});
 const input=fixture(entries[0]);
 for(const tail of ['/bins','/logs','/payment'])await test('oppwa','ignore-'+tail.slice(1),'reveal.star',{...input,path:input.path+tail},{verify:r=>{assert.equal(r.body,input.body);assert.deepEqual(r.reveals,[]);}});
 await test('oppwa','encoding-and-unrelated-fields','reveal.star',{...input,body:'%63ard%2Enumber=4242424242424242&card.cvv=999&note=a%2Bb+c%26d'},{verify:r=>{assert.equal(r.body,'%63ard%2Enumber=4111111111111111&card.cvv=123&note=a%2Bb+c%26d');assert.deepEqual(r.reveals,['4242424242424242','999']);}});
 await test('oppwa','blank-fields','reveal.star',{...input,body:'card.number=&card.cvv='},{verify:r=>assert.deepEqual(r.reveals,[])});
 await test('oppwa','vault-failure','reveal.star',{...input,vault:{}},{error:'ALIAS_UNAVAILABLE'});
}
