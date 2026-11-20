import {finish} from './testing/harness.mjs';
const i=process.argv.indexOf('--provider');
const selected=i<0?null:process.argv[i+1];
if(selected&&!['adyen','cybersource','stripe','oppwa'].includes(selected))throw new Error('Unknown provider');
for(const provider of ['adyen','cybersource','stripe','oppwa']){
 if(selected&&selected!==provider)continue;
 const {run}=await import(`./${provider}/tests.mjs`);await run();
}
await finish();
