import assert from 'node:assert/strict';
import {test,har,fixture,adyenKey,decrypt} from '../testing/harness.mjs';
export async function run(){
 const page=fixture((await har('adyen','capture'))[0],'response');
 page.body=page.body.replace('10001|'+'ab'.repeat(256),adyenKey);
 let captured;
 await test('adyen','capture','capture.star',page,{verify:r=>{assert.equal(r.body,page.body);assert.equal(r.values.adyen_public_key,adyenKey);assert.equal(r.values.adyen_encryption_format,'RSA-OAEP-256/A256GCM');assert.deepEqual(r.reveals,[]);captured=r.values;}});
 await test('adyen','capture-unrelated','capture.star',{...page,body:'<html>unrelated</html>'},{verify:r=>{assert.deepEqual(r.values,{});assert.deepEqual(r.reveals,[]);}});
 const request={...fixture((await har('adyen','encrypt'))[0]),captured,inputs:{data_selector:'$.adyenData.encryptedAdyenForm',card_number_selector:'$.encryptedCardNumber',card_cvc_selector:'$.encryptedSecurityCode',expiry_month_selector:'$.encryptedExpiryMonth',expiry_year_selector:'$.encryptedExpiryYear'}};
 await test('adyen','non-card','encrypt.star',{...request,body:'{"keep":"unchanged"}'},{verify:r=>{assert.equal(r.body,'{"keep":"unchanged"}');assert.deepEqual(r.reveals,[]);}});
 await test('adyen','missing-key','encrypt.star',{...request,captured:{}},{error:'Adyen key unavailable'});
 await test('adyen','missing-format','encrypt.star',{...request,captured:{adyen_public_key:adyenKey,adyen_generationtime:'2030-01-01T00:00:00Z'}},{error:'Adyen encryption format unavailable'});
 for(const role of ['both','number','cvc']){
  const body=JSON.parse(request.body);const fields=body.adyenData.encryptedAdyenForm;
  if(role==='number')delete fields.encryptedSecurityCode;
  if(role==='cvc')delete fields.encryptedCardNumber;
  await test('adyen','encrypt-'+role,'encrypt.star',{...request,body:JSON.stringify(body)},{crypto:true,verify:r=>{
   const result=JSON.parse(r.body);const card=result.adyenData.encryptedAdyenForm;
   if(role!=='cvc')assert.deepEqual(decrypt(card.encryptedCardNumber,'RSA-OAEP-256'),{number:'4111111111111111',generationtime:'2030-01-01T00:00:00Z'});
   if(role!=='number')assert.deepEqual(decrypt(card.encryptedSecurityCode,'RSA-OAEP-256'),{cvc:'123',generationtime:'2030-01-01T00:00:00Z'});
   assert.equal(card.encryptedExpiryMonth,fields.encryptedExpiryMonth);assert.equal(card.encryptedExpiryYear,fields.encryptedExpiryYear);assert.equal(result.order,'synthetic-order');
   assert.deepEqual(r.reveals,role==='both'?['synthetic_pan_alias','synthetic_cvc_alias']:[role==='number'?'synthetic_pan_alias':'synthetic_cvc_alias']);
  }});
 }
}
