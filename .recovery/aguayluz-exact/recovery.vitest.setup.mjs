import { vi, expect } from "vitest";

expect.extend({
  toBeTrue(received){ return {pass:received===true,message:()=>`expected ${received} to be true`}; },
  toBeFalse(received){ return {pass:received===false,message:()=>`expected ${received} to be false`}; },
  toHaveSize(received,expected){
    const actual = received?.size ?? received?.length;
    return {pass:actual===expected,message:()=>`expected size ${expected}, received ${actual}`};
  },
  toThrowError(received, expectedError, expectedMessage){
    if(typeof received!=="function") return {pass:false,message:()=> "expected a function"};
    let thrown;
    try { received(); } catch (e) { thrown=e; }
    let pass=Boolean(thrown);
    if(pass && typeof expectedError==="function") pass = thrown instanceof expectedError;
    else if(pass && expectedError instanceof RegExp) pass = expectedError.test(String(thrown?.message ?? thrown));
    else if(pass && typeof expectedError==="string") pass = String(thrown?.message ?? thrown).includes(expectedError);
    if(pass && expectedMessage instanceof RegExp) pass = expectedMessage.test(String(thrown?.message ?? thrown));
    else if(pass && typeof expectedMessage==="string") pass = String(thrown?.message ?? thrown).includes(expectedMessage);
    return {pass,message:()=> pass ? "expected function not to throw matching error" : `expected matching thrown error, received ${String(thrown)}`};
  },
});

function compat(spy){
  const api=spy;
  api.and={
    returnValue(v){spy.mockReturnValue(v);return api;},
    resolveTo(v){spy.mockResolvedValue(v);return api;},
    callFake(fn){spy.mockImplementation(fn);return api;},
  };
  api.calls={
    mostRecent(){return {args:spy.mock.calls.at(-1)??[]};},
    count(){return spy.mock.calls.length;},
  };
  return api;
}
globalThis.spyOn=(target,key)=>compat(vi.spyOn(target,key));
globalThis.jasmine={
  createSpy(name){return compat(vi.fn().mockName(name));},
  any(ctor){return expect.any(ctor);},
  objectContaining(obj){return expect.objectContaining(obj);},
};
if(typeof window!=="undefined"){
  Object.defineProperty(window,"matchMedia",{configurable:true,writable:true,value:(query)=>({
    matches:false,media:query,onchange:null,addListener(){},removeListener(){},
    addEventListener(){},removeEventListener(){},dispatchEvent(){return false},
  })});
}
