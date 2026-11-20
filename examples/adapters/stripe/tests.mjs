import assert from 'node:assert/strict';
import {test,har,fixture} from '../testing/harness.mjs';
export async function run(){
 const input=fixture((await har('stripe','reveal'))[0]);
 await test('stripe','har-card-fields','reveal.star',input,{verify:r=>{assert.equal(r.body,input.body.replace('4242+4242+4242+4242','4111111111111111').replace('=999&','=123&'));assert.deepEqual(r.reveals,['4242424242424242','999']);}});
 for(const [name,body,expected,submitted] of [
  ['partial-cvc','card%5Bcvc%5D=999','card%5Bcvc%5D=123',['999']],
  ['repeated-pan','card[number]=4242424242424242&card[number]=4242424242424242','card[number]=4111111111111111&card[number]=4111111111111111',['4242424242424242','4242424242424242']],
  ['non-card','payment_method=pm_SYNTHETIC','payment_method=pm_SYNTHETIC',[]],
  ['blank-fields','card[number]=&card[cvc]=','card[number]=&card[cvc]=',[]],
  ['preserve-other-fields','card[cvc]=999&note=a%2Bb+c%26d&card[exp_year]=30','card[cvc]=123&note=a%2Bb+c%26d&card[exp_year]=30',['999']],
 ])await test('stripe',name,'reveal.star',{...input,body},{verify:r=>{assert.equal(r.body,expected);assert.deepEqual(r.reveals,submitted);}});
 await test('stripe','vault-failure','reveal.star',{...input,vault:{}},{error:'ALIAS_UNAVAILABLE'});
}
