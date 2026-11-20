// Execute published VGS Compute source in Starlarky, with explicit host doubles.
// No gateway, merchant, vault, or network access is used by these tests.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createHash,generateKeyPairSync,privateDecrypt,createDecipheriv,constants} from 'node:crypto';

export const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const hash=value=>createHash('sha256').update(value).digest('hex');
const option=name=>{const i=process.argv.indexOf(name);return i<0?null:process.argv[i+1];};
const runtime=option('--runtime-dir');
if(!runtime||!path.isAbsolute(runtime))throw new Error('Supply --runtime-dir /absolute/path/to/runtime. See README.md.');
const includeJvm=process.argv.includes('--jvm');
const nativeImage='debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc';
const jvmImage='maven@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320';
assert.equal(hash(await fs.readFile(path.join(runtime,'larky-1.0.0-linux'))),'9a2d9f179984f2e019132e04e9fdc5d17e21d1f1e9cd12581018519acf7f34b3','Native runtime checksum');
const jvmPlatform=option('--jvm-platform')??(os.arch()==='arm64'?'linux/arm64':'linux/amd64');
if(includeJvm){
 const build=JSON.parse(await fs.readFile(path.join(runtime,'jvm/build.json')));
 assert.equal(build.sourceModified,false);
 assert.equal(build.sourceArchiveSha256,'57e6799d904c047f17f0921e6d3b0696a4965d19c0a18e52a0f2e8d4cb13ef18');
 assert(Object.keys(build.files).some(name=>name.startsWith('runlarky-')));
 for(const [file,sha] of Object.entries(build.files))assert.equal(hash(await fs.readFile(path.join(runtime,'jvm',file))),sha,`JVM dependency checksum: ${file}`);
}
process.umask(0o077);
const output=await fs.mkdtemp(path.join(os.tmpdir(),'awg-public-examples-'));
const report={scope:'Synthetic fixtures; real function source; offline message/session/vault doubles. No gateway or merchant acceptance claim.',cases:[],sourceHashes:{},fixtureHashes:{},nativeCryptoLimitations:[],output};
const doubles=await fs.readFile(path.join(root,'testing/host-doubles.star'),'utf8');
const pair=generateKeyPairSync('rsa',{modulusLength:2048});
export const jwk={...pair.publicKey.export({format:'jwk'}),kid:'synthetic-key'};
export const adyenKey='10001|'+Buffer.from(jwk.n,'base64url').toString('hex');
export const segment=value=>Buffer.from(JSON.stringify(value)).toString('base64url');
export const context=segment({alg:'RS256',typ:'JWT'})+'.'+segment({flx:{origin:'https://flex.cybersource.com',path:'/flex/v2/tokens',jwk},exp:1893456000})+'.synthetic';
export const relay=value=>'AWGCS1:'+Array.from(Buffer.from(JSON.stringify(value)),b=>String.fromCharCode(97+(b>>4),97+(b&15))).join('');
export function decrypt(value,algorithm){
 const parts=value.split('.');assert.equal(parts.length,5);
 const header=JSON.parse(Buffer.from(parts[0],'base64url'));
 assert.equal(header.alg,algorithm);assert.equal(header.enc,'A256GCM');
 const cek=privateDecrypt({key:pair.privateKey,oaepHash:algorithm==='RSA-OAEP'?'sha1':'sha256',padding:constants.RSA_PKCS1_OAEP_PADDING},Buffer.from(parts[1],'base64url'));
 const cipher=createDecipheriv('aes-256-gcm',cek,Buffer.from(parts[2],'base64url'));
 cipher.setAAD(Buffer.from(parts[0]));cipher.setAuthTag(Buffer.from(parts[4],'base64url'));
 return JSON.parse(Buffer.concat([cipher.update(Buffer.from(parts[3],'base64url')),cipher.final()]));
}
export async function har(provider,functionName){
 const data=await fs.readFile(path.join(root,provider,'fixtures',functionName+'.synthetic.har'));
 report.fixtureHashes[`${provider}/${functionName}`]=hash(data);
 return JSON.parse(data).log.entries;
}
export function fixture(entry,phase='request'){
 const message=entry[phase];
 return {body:phase==='response'?message.content.text:message.postData.text,
  path:new URL(entry.request.url).pathname,headers:message.headers.map(h=>[h.name,h.value]),
  vault:{'4242424242424242':'4111111111111111','999':'123',synthetic_pan_alias:'4111111111111111',synthetic_cvc_alias:'123'}};
}
async function command(args){
 return await new Promise((resolve,reject)=>{
  const child=spawn('docker',args);let log='';
  const timer=setTimeout(()=>child.kill('SIGKILL'),60000);
  child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
  child.on('error',error=>{clearTimeout(timer);reject(error);});
  child.on('close',code=>{clearTimeout(timer);resolve({code,log});});
 });
}
export async function test(provider,name,sourceName,input,{error,crypto=false,verify=()=>{}}={}){
 const source=await fs.readFile(path.join(root,provider,'functions',sourceName),'utf8');
 report.sourceHashes[`${provider}/${sourceName}`]=hash(source);
 // Only imports for unavailable host interfaces and the injected resolver placeholder change.
 const logic=source.replace(/^load\("@vgs\/\/(?:vault|agent_gateway)", (?:vault|session)="(?:vault|session)"\)\r?\n/gm,'').replace(/^adapter_input = None\r?\n/gm,'');
 const combined=doubles+'\n'+logic+'\nprocess(message, {})\nprint("LARKY_CASE_PASSED")\njson.dumps(_test_state)\n';
 const loads=[...new Set([...combined.matchAll(/^load\([^\n]+\)$/gm)].map(m=>m[0]))];
 const script=loads.join('\n')+'\n'+combined.replace(/^load\([^\n]+\)\n/gm,'');
 for(const engine of crypto&&includeJvm?['native','jvm']:['native']){
  const dir=path.join(output,`${String(report.cases.length).padStart(3,'0')}-${provider}-${name}-${engine}`);await fs.mkdir(dir);
  const data={...input,bodyHex:Buffer.from(input.body).toString('hex')};
  await fs.writeFile(path.join(dir,'input.star'),'load("@stdlib//json", json="json")\ncapture=json.loads('+JSON.stringify(JSON.stringify(data))+')\n');
  await fs.writeFile(path.join(dir,'test.star'),script);
  const executable=engine==='native'?['/runtime/larky-1.0.0-linux']:['java','-XX:ActiveProcessorCount=1','-Xmx256m','-cp','/runtime/jvm/*','com.verygood.security.run.LarkyEntrypoint'];
  const args=['run','--rm','--pull=never','--platform',engine==='native'?'linux/amd64':jvmPlatform,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','512m','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--mount',`type=bind,source=${runtime},target=/runtime,readonly`,'--mount',`type=bind,source=${dir},target=/work`,engine==='native'?nativeImage:jvmImage,...executable,'-i','/work/input.star','-s','/work/test.star','-o','/work/output.txt','-l','/work/run.log'];
  const result=await command(args);await fs.writeFile(path.join(dir,'console.log'),result.log);
  if(crypto&&engine==='native'&&result.code!==0&&result.log.includes('BuiltinTypeFunction missing getStarlarkType')){
   report.nativeCryptoLimitations.push({provider,name,reason:'Pinned native runtime JOSE reflection failure'});
   report.cases.push({provider,name,engine,status:'limited'});console.log('LIMIT',engine,provider,name);continue;
  }
  try{
   if(error){assert(![0,125,126,127,null].includes(result.code));assert(result.log.includes(error));assert(!result.log.includes('LARKY_CASE_PASSED'));}
   else{
    assert.equal(result.code,0,`Runtime failed; see ${dir}/console.log`);assert(result.log.includes('LARKY_CASE_PASSED'));
    let value=JSON.parse(await fs.readFile(path.join(dir,'output.txt'),'utf8'));if(typeof value==='string')value=JSON.parse(value);
    verify(value);
   }
   report.cases.push({provider,name,engine,status:'passed'});console.log('PASS',engine,provider,name);
  }catch(failure){report.cases.push({provider,name,engine,status:'failed',diagnostic:dir});console.log('FAIL',engine,provider,name);await fs.writeFile(path.join(dir,'assertion.txt'),failure.stack);}
 }
}

export async function finish(){
report.passed=report.cases.filter(c=>c.status==='passed').length;
report.failed=report.cases.filter(c=>c.status==='failed').length;
await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');
console.log(`${report.passed} passed; ${report.failed} failed; ${report.nativeCryptoLimitations.length} native crypto limitations. Report: ${output}/report.json`);
process.exitCode=report.failed?1:0;
}
