(() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __commonJS = (cb, mod) => function __require() {
    try {
      return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
    } catch (e) {
      throw mod = 0, e;
    }
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));

  // node_modules/onigasm/lib/onigasm.js
  var require_onigasm = __commonJS({
    "node_modules/onigasm/lib/onigasm.js"(exports, module) {
      var Onigasm = (function() {
        var _scriptDir = typeof document !== "undefined" && document.currentScript ? document.currentScript.src : void 0;
        return (function(Onigasm2) {
          Onigasm2 = Onigasm2 || {};
          var Module = typeof Onigasm2 !== "undefined" ? Onigasm2 : {};
          var moduleOverrides = {};
          var key;
          for (key in Module) {
            if (Module.hasOwnProperty(key)) {
              moduleOverrides[key] = Module[key];
            }
          }
          var arguments_ = [];
          var thisProgram = "./this.program";
          var quit_ = function(status, toThrow) {
            throw toThrow;
          };
          var ENVIRONMENT_IS_WEB = false;
          var ENVIRONMENT_IS_WORKER = false;
          var ENVIRONMENT_IS_NODE = false;
          var ENVIRONMENT_IS_SHELL = true;
          var scriptDirectory = "";
          function locateFile(path) {
            if (Module["locateFile"]) {
              return Module["locateFile"](path, scriptDirectory);
            }
            return scriptDirectory + path;
          }
          var read_, readBinary;
          if (ENVIRONMENT_IS_SHELL) {
            if (typeof read != "undefined") {
              read_ = function shell_read(f) {
                return read(f);
              };
            }
            readBinary = function readBinary2(f) {
              var data;
              if (typeof readbuffer === "function") {
                return new Uint8Array(readbuffer(f));
              }
              data = read(f, "binary");
              assert(typeof data === "object");
              return data;
            };
            if (typeof scriptArgs != "undefined") {
              arguments_ = scriptArgs;
            } else if (typeof arguments != "undefined") {
              arguments_ = arguments;
            }
            if (typeof quit === "function") {
              quit_ = function(status) {
                quit(status);
              };
            }
            if (typeof print !== "undefined") {
              if (typeof console === "undefined") console = {};
              console.log = print;
              console.warn = console.error = typeof printErr !== "undefined" ? printErr : print;
            }
          } else {
          }
          var out = Module["print"] || console.log.bind(console);
          var err = Module["printErr"] || console.warn.bind(console);
          for (key in moduleOverrides) {
            if (moduleOverrides.hasOwnProperty(key)) {
              Module[key] = moduleOverrides[key];
            }
          }
          moduleOverrides = null;
          if (Module["arguments"]) arguments_ = Module["arguments"];
          if (Module["thisProgram"]) thisProgram = Module["thisProgram"];
          if (Module["quit"]) quit_ = Module["quit"];
          var STACK_ALIGN = 16;
          function dynamicAlloc(size) {
            var ret = HEAP32[DYNAMICTOP_PTR >> 2];
            var end = ret + size + 15 & -16;
            if (end > _emscripten_get_heap_size()) {
              abort();
            }
            HEAP32[DYNAMICTOP_PTR >> 2] = end;
            return ret;
          }
          function getNativeTypeSize(type) {
            switch (type) {
              case "i1":
              case "i8":
                return 1;
              case "i16":
                return 2;
              case "i32":
                return 4;
              case "i64":
                return 8;
              case "float":
                return 4;
              case "double":
                return 8;
              default: {
                if (type[type.length - 1] === "*") {
                  return 4;
                } else if (type[0] === "i") {
                  var bits = parseInt(type.substr(1));
                  assert(bits % 8 === 0, "getNativeTypeSize invalid bits " + bits + ", type " + type);
                  return bits / 8;
                } else {
                  return 0;
                }
              }
            }
          }
          function warnOnce(text) {
            if (!warnOnce.shown) warnOnce.shown = {};
            if (!warnOnce.shown[text]) {
              warnOnce.shown[text] = 1;
              err(text);
            }
          }
          function convertJsFunctionToWasm(func, sig) {
            var typeSection = [1, 0, 1, 96];
            var sigRet = sig.slice(0, 1);
            var sigParam = sig.slice(1);
            var typeCodes = { "i": 127, "j": 126, "f": 125, "d": 124 };
            typeSection.push(sigParam.length);
            for (var i = 0; i < sigParam.length; ++i) {
              typeSection.push(typeCodes[sigParam[i]]);
            }
            if (sigRet == "v") {
              typeSection.push(0);
            } else {
              typeSection = typeSection.concat([1, typeCodes[sigRet]]);
            }
            typeSection[1] = typeSection.length - 2;
            var bytes = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0].concat(typeSection, [2, 7, 1, 1, 101, 1, 102, 0, 0, 7, 5, 1, 1, 102, 0, 0]));
            var module2 = new WebAssembly.Module(bytes);
            var instance = new WebAssembly.Instance(module2, { e: { f: func } });
            var wrappedFunc = instance.exports.f;
            return wrappedFunc;
          }
          function addFunctionWasm(func, sig) {
            var table = wasmTable;
            var ret = table.length;
            try {
              table.grow(1);
            } catch (err2) {
              if (!err2 instanceof RangeError) {
                throw err2;
              }
              throw "Unable to grow wasm table. Use a higher value for RESERVED_FUNCTION_POINTERS or set ALLOW_TABLE_GROWTH.";
            }
            try {
              table.set(ret, func);
            } catch (err2) {
              if (!err2 instanceof TypeError) {
                throw err2;
              }
              assert(typeof sig !== "undefined", "Missing signature argument to addFunction");
              var wrapped = convertJsFunctionToWasm(func, sig);
              table.set(ret, wrapped);
            }
            return ret;
          }
          function removeFunctionWasm(index) {
          }
          var funcWrappers = {};
          function dynCall(sig, ptr, args) {
            if (args && args.length) {
              return Module["dynCall_" + sig].apply(null, [ptr].concat(args));
            } else {
              return Module["dynCall_" + sig].call(null, ptr);
            }
          }
          var tempRet0 = 0;
          var setTempRet0 = function(value) {
            tempRet0 = value;
          };
          var wasmBinary;
          if (Module["wasmBinary"]) wasmBinary = Module["wasmBinary"];
          var noExitRuntime;
          if (Module["noExitRuntime"]) noExitRuntime = Module["noExitRuntime"];
          if (typeof WebAssembly !== "object") {
            err("no native wasm support detected");
          }
          function setValue(ptr, value, type, noSafe) {
            type = type || "i8";
            if (type.charAt(type.length - 1) === "*") type = "i32";
            switch (type) {
              case "i1":
                HEAP8[ptr >> 0] = value;
                break;
              case "i8":
                HEAP8[ptr >> 0] = value;
                break;
              case "i16":
                HEAP16[ptr >> 1] = value;
                break;
              case "i32":
                HEAP32[ptr >> 2] = value;
                break;
              case "i64":
                tempI64 = [value >>> 0, (tempDouble = value, +Math_abs(tempDouble) >= 1 ? tempDouble > 0 ? (Math_min(+Math_floor(tempDouble / 4294967296), 4294967295) | 0) >>> 0 : ~~+Math_ceil((tempDouble - +(~~tempDouble >>> 0)) / 4294967296) >>> 0 : 0)], HEAP32[ptr >> 2] = tempI64[0], HEAP32[ptr + 4 >> 2] = tempI64[1];
                break;
              case "float":
                HEAPF32[ptr >> 2] = value;
                break;
              case "double":
                HEAPF64[ptr >> 3] = value;
                break;
              default:
                abort("invalid type for setValue: " + type);
            }
          }
          var wasmMemory;
          var wasmTable = new WebAssembly.Table({ "initial": 244, "maximum": 244 + 0, "element": "anyfunc" });
          var ABORT = false;
          var EXITSTATUS = 0;
          function assert(condition, text) {
            if (!condition) {
              abort("Assertion failed: " + text);
            }
          }
          function getCFunc(ident) {
            var func = Module["_" + ident];
            assert(func, "Cannot call unknown function " + ident + ", make sure it is exported");
            return func;
          }
          function ccall(ident, returnType, argTypes, args, opts) {
            var toC = { "string": function(str) {
              var ret2 = 0;
              if (str !== null && str !== void 0 && str !== 0) {
                var len = (str.length << 2) + 1;
                ret2 = stackAlloc(len);
                stringToUTF8(str, ret2, len);
              }
              return ret2;
            }, "array": function(arr) {
              var ret2 = stackAlloc(arr.length);
              writeArrayToMemory(arr, ret2);
              return ret2;
            } };
            function convertReturnValue(ret2) {
              if (returnType === "string") return UTF8ToString(ret2);
              if (returnType === "boolean") return Boolean(ret2);
              return ret2;
            }
            var func = getCFunc(ident);
            var cArgs = [];
            var stack = 0;
            if (args) {
              for (var i = 0; i < args.length; i++) {
                var converter = toC[argTypes[i]];
                if (converter) {
                  if (stack === 0) stack = stackSave();
                  cArgs[i] = converter(args[i]);
                } else {
                  cArgs[i] = args[i];
                }
              }
            }
            var ret = func.apply(null, cArgs);
            ret = convertReturnValue(ret);
            if (stack !== 0) stackRestore(stack);
            return ret;
          }
          var ALLOC_NONE = 3;
          var UTF8Decoder = typeof TextDecoder !== "undefined" ? new TextDecoder("utf8") : void 0;
          function UTF8ArrayToString(u8Array, idx, maxBytesToRead) {
            var endIdx = idx + maxBytesToRead;
            var endPtr = idx;
            while (u8Array[endPtr] && !(endPtr >= endIdx)) ++endPtr;
            if (endPtr - idx > 16 && u8Array.subarray && UTF8Decoder) {
              return UTF8Decoder.decode(u8Array.subarray(idx, endPtr));
            } else {
              var str = "";
              while (idx < endPtr) {
                var u0 = u8Array[idx++];
                if (!(u0 & 128)) {
                  str += String.fromCharCode(u0);
                  continue;
                }
                var u1 = u8Array[idx++] & 63;
                if ((u0 & 224) == 192) {
                  str += String.fromCharCode((u0 & 31) << 6 | u1);
                  continue;
                }
                var u2 = u8Array[idx++] & 63;
                if ((u0 & 240) == 224) {
                  u0 = (u0 & 15) << 12 | u1 << 6 | u2;
                } else {
                  u0 = (u0 & 7) << 18 | u1 << 12 | u2 << 6 | u8Array[idx++] & 63;
                }
                if (u0 < 65536) {
                  str += String.fromCharCode(u0);
                } else {
                  var ch = u0 - 65536;
                  str += String.fromCharCode(55296 | ch >> 10, 56320 | ch & 1023);
                }
              }
            }
            return str;
          }
          function UTF8ToString(ptr, maxBytesToRead) {
            return ptr ? UTF8ArrayToString(HEAPU8, ptr, maxBytesToRead) : "";
          }
          function stringToUTF8Array(str, outU8Array, outIdx, maxBytesToWrite) {
            if (!(maxBytesToWrite > 0)) return 0;
            var startIdx = outIdx;
            var endIdx = outIdx + maxBytesToWrite - 1;
            for (var i = 0; i < str.length; ++i) {
              var u = str.charCodeAt(i);
              if (u >= 55296 && u <= 57343) {
                var u1 = str.charCodeAt(++i);
                u = 65536 + ((u & 1023) << 10) | u1 & 1023;
              }
              if (u <= 127) {
                if (outIdx >= endIdx) break;
                outU8Array[outIdx++] = u;
              } else if (u <= 2047) {
                if (outIdx + 1 >= endIdx) break;
                outU8Array[outIdx++] = 192 | u >> 6;
                outU8Array[outIdx++] = 128 | u & 63;
              } else if (u <= 65535) {
                if (outIdx + 2 >= endIdx) break;
                outU8Array[outIdx++] = 224 | u >> 12;
                outU8Array[outIdx++] = 128 | u >> 6 & 63;
                outU8Array[outIdx++] = 128 | u & 63;
              } else {
                if (outIdx + 3 >= endIdx) break;
                outU8Array[outIdx++] = 240 | u >> 18;
                outU8Array[outIdx++] = 128 | u >> 12 & 63;
                outU8Array[outIdx++] = 128 | u >> 6 & 63;
                outU8Array[outIdx++] = 128 | u & 63;
              }
            }
            outU8Array[outIdx] = 0;
            return outIdx - startIdx;
          }
          function stringToUTF8(str, outPtr, maxBytesToWrite) {
            return stringToUTF8Array(str, HEAPU8, outPtr, maxBytesToWrite);
          }
          function lengthBytesUTF8(str) {
            var len = 0;
            for (var i = 0; i < str.length; ++i) {
              var u = str.charCodeAt(i);
              if (u >= 55296 && u <= 57343) u = 65536 + ((u & 1023) << 10) | str.charCodeAt(++i) & 1023;
              if (u <= 127) ++len;
              else if (u <= 2047) len += 2;
              else if (u <= 65535) len += 3;
              else len += 4;
            }
            return len;
          }
          var UTF16Decoder = typeof TextDecoder !== "undefined" ? new TextDecoder("utf-16le") : void 0;
          function writeArrayToMemory(array, buffer2) {
            HEAP8.set(array, buffer2);
          }
          function writeAsciiToMemory(str, buffer2, dontAddNull) {
            for (var i = 0; i < str.length; ++i) {
              HEAP8[buffer2++ >> 0] = str.charCodeAt(i);
            }
            if (!dontAddNull) HEAP8[buffer2 >> 0] = 0;
          }
          var WASM_PAGE_SIZE = 65536;
          function alignUp(x, multiple) {
            if (x % multiple > 0) {
              x += multiple - x % multiple;
            }
            return x;
          }
          var buffer, HEAP8, HEAPU8, HEAP16, HEAPU16, HEAP32, HEAPU32, HEAPF32, HEAPF64;
          function updateGlobalBufferAndViews(buf) {
            buffer = buf;
            Module["HEAP8"] = HEAP8 = new Int8Array(buf);
            Module["HEAP16"] = HEAP16 = new Int16Array(buf);
            Module["HEAP32"] = HEAP32 = new Int32Array(buf);
            Module["HEAPU8"] = HEAPU8 = new Uint8Array(buf);
            Module["HEAPU16"] = HEAPU16 = new Uint16Array(buf);
            Module["HEAPU32"] = HEAPU32 = new Uint32Array(buf);
            Module["HEAPF32"] = HEAPF32 = new Float32Array(buf);
            Module["HEAPF64"] = HEAPF64 = new Float64Array(buf);
          }
          var STACK_BASE = 5507664, DYNAMIC_BASE = 5507664, DYNAMICTOP_PTR = 264624;
          var INITIAL_TOTAL_MEMORY = Module["TOTAL_MEMORY"] || 157286400;
          if (Module["wasmMemory"]) {
            wasmMemory = Module["wasmMemory"];
          } else {
            wasmMemory = new WebAssembly.Memory({ "initial": INITIAL_TOTAL_MEMORY / WASM_PAGE_SIZE });
          }
          if (wasmMemory) {
            buffer = wasmMemory.buffer;
          }
          INITIAL_TOTAL_MEMORY = buffer.byteLength;
          updateGlobalBufferAndViews(buffer);
          HEAP32[DYNAMICTOP_PTR >> 2] = DYNAMIC_BASE;
          function callRuntimeCallbacks(callbacks) {
            while (callbacks.length > 0) {
              var callback = callbacks.shift();
              if (typeof callback == "function") {
                callback();
                continue;
              }
              var func = callback.func;
              if (typeof func === "number") {
                if (callback.arg === void 0) {
                  Module["dynCall_v"](func);
                } else {
                  Module["dynCall_vi"](func, callback.arg);
                }
              } else {
                func(callback.arg === void 0 ? null : callback.arg);
              }
            }
          }
          var __ATPRERUN__ = [];
          var __ATINIT__ = [];
          var __ATMAIN__ = [];
          var __ATPOSTRUN__ = [];
          var runtimeInitialized = false;
          var runtimeExited = false;
          function preRun() {
            if (Module["preRun"]) {
              if (typeof Module["preRun"] == "function") Module["preRun"] = [Module["preRun"]];
              while (Module["preRun"].length) {
                addOnPreRun(Module["preRun"].shift());
              }
            }
            callRuntimeCallbacks(__ATPRERUN__);
          }
          function initRuntime() {
            runtimeInitialized = true;
            callRuntimeCallbacks(__ATINIT__);
          }
          function preMain() {
            callRuntimeCallbacks(__ATMAIN__);
          }
          function exitRuntime() {
            runtimeExited = true;
          }
          function postRun() {
            if (Module["postRun"]) {
              if (typeof Module["postRun"] == "function") Module["postRun"] = [Module["postRun"]];
              while (Module["postRun"].length) {
                addOnPostRun(Module["postRun"].shift());
              }
            }
            callRuntimeCallbacks(__ATPOSTRUN__);
          }
          function addOnPreRun(cb) {
            __ATPRERUN__.unshift(cb);
          }
          function addOnPostRun(cb) {
            __ATPOSTRUN__.unshift(cb);
          }
          var Math_abs = Math.abs;
          var Math_ceil = Math.ceil;
          var Math_floor = Math.floor;
          var Math_min = Math.min;
          var runDependencies = 0;
          var runDependencyWatcher = null;
          var dependenciesFulfilled = null;
          function addRunDependency(id) {
            runDependencies++;
            if (Module["monitorRunDependencies"]) {
              Module["monitorRunDependencies"](runDependencies);
            }
          }
          function removeRunDependency(id) {
            runDependencies--;
            if (Module["monitorRunDependencies"]) {
              Module["monitorRunDependencies"](runDependencies);
            }
            if (runDependencies == 0) {
              if (runDependencyWatcher !== null) {
                clearInterval(runDependencyWatcher);
                runDependencyWatcher = null;
              }
              if (dependenciesFulfilled) {
                var callback = dependenciesFulfilled;
                dependenciesFulfilled = null;
                callback();
              }
            }
          }
          Module["preloadedImages"] = {};
          Module["preloadedAudios"] = {};
          function abort(what) {
            if (Module["onAbort"]) {
              Module["onAbort"](what);
            }
            what += "";
            out(what);
            err(what);
            ABORT = true;
            EXITSTATUS = 1;
            what = "abort(" + what + "). Build with -s ASSERTIONS=1 for more info.";
            throw new WebAssembly.RuntimeError(what);
          }
          var dataURIPrefix = "data:application/octet-stream;base64,";
          function isDataURI(filename) {
            return String.prototype.startsWith ? filename.startsWith(dataURIPrefix) : filename.indexOf(dataURIPrefix) === 0;
          }
          var wasmBinaryFile = "onigasm.wasm";
          if (!isDataURI(wasmBinaryFile)) {
            wasmBinaryFile = locateFile(wasmBinaryFile);
          }
          function getBinary() {
            try {
              if (wasmBinary) {
                return new Uint8Array(wasmBinary);
              }
              if (readBinary) {
                return readBinary(wasmBinaryFile);
              } else {
                throw "both async and sync fetching of the wasm failed";
              }
            } catch (err2) {
              abort(err2);
            }
          }
          function getBinaryPromise() {
            if (!wasmBinary && (ENVIRONMENT_IS_WEB || ENVIRONMENT_IS_WORKER) && typeof fetch === "function") {
              return fetch(wasmBinaryFile, { credentials: "same-origin" }).then(function(response) {
                if (!response["ok"]) {
                  throw "failed to load wasm binary file at '" + wasmBinaryFile + "'";
                }
                return response["arrayBuffer"]();
              }).catch(function() {
                return getBinary();
              });
            }
            return new Promise(function(resolve, reject) {
              resolve(getBinary());
            });
          }
          function createWasm() {
            var info = { "env": asmLibraryArg, "wasi_unstable": asmLibraryArg };
            function receiveInstance(instance, module2) {
              var exports3 = instance.exports;
              Module["asm"] = exports3;
              removeRunDependency("wasm-instantiate");
            }
            addRunDependency("wasm-instantiate");
            function receiveInstantiatedSource(output) {
              receiveInstance(output["instance"]);
            }
            function instantiateArrayBuffer(receiver) {
              return getBinaryPromise().then(function(binary) {
                return WebAssembly.instantiate(binary, info);
              }).then(receiver, function(reason) {
                err("failed to asynchronously prepare wasm: " + reason);
                abort(reason);
              });
            }
            function instantiateAsync() {
              if (!wasmBinary && typeof WebAssembly.instantiateStreaming === "function" && !isDataURI(wasmBinaryFile) && typeof fetch === "function") {
                fetch(wasmBinaryFile, { credentials: "same-origin" }).then(function(response) {
                  var result = WebAssembly.instantiateStreaming(response, info);
                  return result.then(receiveInstantiatedSource, function(reason) {
                    err("wasm streaming compile failed: " + reason);
                    err("falling back to ArrayBuffer instantiation");
                    instantiateArrayBuffer(receiveInstantiatedSource);
                  });
                });
              } else {
                return instantiateArrayBuffer(receiveInstantiatedSource);
              }
            }
            if (Module["instantiateWasm"]) {
              try {
                var exports2 = Module["instantiateWasm"](info, receiveInstance);
                return exports2;
              } catch (e) {
                err("Module.instantiateWasm callback failed with error: " + e);
                return false;
              }
            }
            instantiateAsync();
            return {};
          }
          var tempDouble;
          var tempI64;
          __ATINIT__.push({ func: function() {
            ___wasm_call_ctors();
          } });
          function demangle(func) {
            var __cxa_demangle_func = Module["___cxa_demangle"] || Module["__cxa_demangle"];
            assert(__cxa_demangle_func);
            try {
              var s = func;
              if (s.startsWith("__Z")) s = s.substr(1);
              var len = lengthBytesUTF8(s) + 1;
              var buf = _malloc(len);
              stringToUTF8(s, buf, len);
              var status = _malloc(4);
              var ret = __cxa_demangle_func(buf, 0, 0, status);
              if (HEAP32[status >> 2] === 0 && ret) {
                return UTF8ToString(ret);
              }
            } catch (e) {
            } finally {
              if (buf) _free(buf);
              if (status) _free(status);
              if (ret) _free(ret);
            }
            return func;
          }
          function demangleAll(text) {
            var regex = /\b_Z[\w\d_]+/g;
            return text.replace(regex, function(x) {
              var y = demangle(x);
              return x === y ? x : y + " [" + x + "]";
            });
          }
          function jsStackTrace() {
            var err2 = new Error();
            if (!err2.stack) {
              try {
                throw new Error(0);
              } catch (e) {
                err2 = e;
              }
              if (!err2.stack) {
                return "(no stack trace available)";
              }
            }
            return err2.stack.toString();
          }
          function _abort() {
            abort();
          }
          function _emscripten_get_heap_size() {
            return HEAP8.length;
          }
          function _emscripten_get_sbrk_ptr() {
            return 264624;
          }
          function _emscripten_memcpy_big(dest, src, num) {
            HEAPU8.set(HEAPU8.subarray(src, src + num), dest);
          }
          function emscripten_realloc_buffer(size) {
            try {
              wasmMemory.grow(size - buffer.byteLength + 65535 >> 16);
              updateGlobalBufferAndViews(wasmMemory.buffer);
              return 1;
            } catch (e) {
            }
          }
          function _emscripten_resize_heap(requestedSize) {
            var oldSize = _emscripten_get_heap_size();
            var PAGE_MULTIPLE = 65536;
            var LIMIT = 2147483648 - PAGE_MULTIPLE;
            if (requestedSize > LIMIT) {
              return false;
            }
            var MIN_TOTAL_MEMORY = 16777216;
            var newSize = Math.max(oldSize, MIN_TOTAL_MEMORY);
            while (newSize < requestedSize) {
              if (newSize <= 536870912) {
                newSize = alignUp(2 * newSize, PAGE_MULTIPLE);
              } else {
                newSize = Math.min(alignUp((3 * newSize + 2147483648) / 4, PAGE_MULTIPLE), LIMIT);
              }
            }
            var replacement = emscripten_realloc_buffer(newSize);
            if (!replacement) {
              return false;
            }
            return true;
          }
          var PATH = { splitPath: function(filename) {
            var splitPathRe = /^(\/?|)([\s\S]*?)((?:\.{1,2}|[^\/]+?|)(\.[^.\/]*|))(?:[\/]*)$/;
            return splitPathRe.exec(filename).slice(1);
          }, normalizeArray: function(parts, allowAboveRoot) {
            var up = 0;
            for (var i = parts.length - 1; i >= 0; i--) {
              var last = parts[i];
              if (last === ".") {
                parts.splice(i, 1);
              } else if (last === "..") {
                parts.splice(i, 1);
                up++;
              } else if (up) {
                parts.splice(i, 1);
                up--;
              }
            }
            if (allowAboveRoot) {
              for (; up; up--) {
                parts.unshift("..");
              }
            }
            return parts;
          }, normalize: function(path) {
            var isAbsolute = path.charAt(0) === "/", trailingSlash = path.substr(-1) === "/";
            path = PATH.normalizeArray(path.split("/").filter(function(p) {
              return !!p;
            }), !isAbsolute).join("/");
            if (!path && !isAbsolute) {
              path = ".";
            }
            if (path && trailingSlash) {
              path += "/";
            }
            return (isAbsolute ? "/" : "") + path;
          }, dirname: function(path) {
            var result = PATH.splitPath(path), root = result[0], dir = result[1];
            if (!root && !dir) {
              return ".";
            }
            if (dir) {
              dir = dir.substr(0, dir.length - 1);
            }
            return root + dir;
          }, basename: function(path) {
            if (path === "/") return "/";
            var lastSlash = path.lastIndexOf("/");
            if (lastSlash === -1) return path;
            return path.substr(lastSlash + 1);
          }, extname: function(path) {
            return PATH.splitPath(path)[3];
          }, join: function() {
            var paths = Array.prototype.slice.call(arguments, 0);
            return PATH.normalize(paths.join("/"));
          }, join2: function(l, r) {
            return PATH.normalize(l + "/" + r);
          } };
          var SYSCALLS = { buffers: [null, [], []], printChar: function(stream, curr) {
            var buffer2 = SYSCALLS.buffers[stream];
            if (curr === 0 || curr === 10) {
              (stream === 1 ? out : err)(UTF8ArrayToString(buffer2, 0));
              buffer2.length = 0;
            } else {
              buffer2.push(curr);
            }
          }, varargs: 0, get: function(varargs) {
            SYSCALLS.varargs += 4;
            var ret = HEAP32[SYSCALLS.varargs - 4 >> 2];
            return ret;
          }, getStr: function() {
            var ret = UTF8ToString(SYSCALLS.get());
            return ret;
          }, get64: function() {
            var low = SYSCALLS.get(), high = SYSCALLS.get();
            return low;
          }, getZero: function() {
            SYSCALLS.get();
          } };
          function _fd_close(fd) {
            try {
              return 0;
            } catch (e) {
              if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
              return e.errno;
            }
          }
          function _fd_seek(fd, offset_low, offset_high, whence, newOffset) {
            try {
              return 0;
            } catch (e) {
              if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
              return e.errno;
            }
          }
          function _fd_write(fd, iov, iovcnt, pnum) {
            try {
              var num = 0;
              for (var i = 0; i < iovcnt; i++) {
                var ptr = HEAP32[iov + i * 8 >> 2];
                var len = HEAP32[iov + (i * 8 + 4) >> 2];
                for (var j = 0; j < len; j++) {
                  SYSCALLS.printChar(fd, HEAPU8[ptr + j]);
                }
                num += len;
              }
              HEAP32[pnum >> 2] = num;
              return 0;
            } catch (e) {
              if (typeof FS === "undefined" || !(e instanceof FS.ErrnoError)) abort(e);
              return e.errno;
            }
          }
          function _setTempRet0($i) {
            setTempRet0($i | 0);
          }
          var ASSERTIONS = false;
          var asmLibraryArg = { "abort": _abort, "emscripten_get_sbrk_ptr": _emscripten_get_sbrk_ptr, "emscripten_memcpy_big": _emscripten_memcpy_big, "emscripten_resize_heap": _emscripten_resize_heap, "fd_close": _fd_close, "fd_seek": _fd_seek, "fd_write": _fd_write, "memory": wasmMemory, "setTempRet0": _setTempRet0, "table": wasmTable };
          var asm = createWasm();
          Module["asm"] = asm;
          var ___wasm_call_ctors = Module["___wasm_call_ctors"] = function() {
            return Module["asm"]["__wasm_call_ctors"].apply(null, arguments);
          };
          var _malloc = Module["_malloc"] = function() {
            return Module["asm"]["malloc"].apply(null, arguments);
          };
          var _free = Module["_free"] = function() {
            return Module["asm"]["free"].apply(null, arguments);
          };
          var _getLastError = Module["_getLastError"] = function() {
            return Module["asm"]["getLastError"].apply(null, arguments);
          };
          var _compilePattern = Module["_compilePattern"] = function() {
            return Module["asm"]["compilePattern"].apply(null, arguments);
          };
          var _disposeCompiledPatterns = Module["_disposeCompiledPatterns"] = function() {
            return Module["asm"]["disposeCompiledPatterns"].apply(null, arguments);
          };
          var _findBestMatch = Module["_findBestMatch"] = function() {
            return Module["asm"]["findBestMatch"].apply(null, arguments);
          };
          var ___cxa_demangle = Module["___cxa_demangle"] = function() {
            return Module["asm"]["__cxa_demangle"].apply(null, arguments);
          };
          var _setThrew = Module["_setThrew"] = function() {
            return Module["asm"]["setThrew"].apply(null, arguments);
          };
          var stackSave = Module["stackSave"] = function() {
            return Module["asm"]["stackSave"].apply(null, arguments);
          };
          var stackAlloc = Module["stackAlloc"] = function() {
            return Module["asm"]["stackAlloc"].apply(null, arguments);
          };
          var stackRestore = Module["stackRestore"] = function() {
            return Module["asm"]["stackRestore"].apply(null, arguments);
          };
          var __growWasmMemory = Module["__growWasmMemory"] = function() {
            return Module["asm"]["__growWasmMemory"].apply(null, arguments);
          };
          var dynCall_vi = Module["dynCall_vi"] = function() {
            return Module["asm"]["dynCall_vi"].apply(null, arguments);
          };
          var dynCall_iiii = Module["dynCall_iiii"] = function() {
            return Module["asm"]["dynCall_iiii"].apply(null, arguments);
          };
          var dynCall_iiiii = Module["dynCall_iiiii"] = function() {
            return Module["asm"]["dynCall_iiiii"].apply(null, arguments);
          };
          var dynCall_iii = Module["dynCall_iii"] = function() {
            return Module["asm"]["dynCall_iii"].apply(null, arguments);
          };
          var dynCall_iidiiii = Module["dynCall_iidiiii"] = function() {
            return Module["asm"]["dynCall_iidiiii"].apply(null, arguments);
          };
          var dynCall_vii = Module["dynCall_vii"] = function() {
            return Module["asm"]["dynCall_vii"].apply(null, arguments);
          };
          var dynCall_ii = Module["dynCall_ii"] = function() {
            return Module["asm"]["dynCall_ii"].apply(null, arguments);
          };
          var dynCall_i = Module["dynCall_i"] = function() {
            return Module["asm"]["dynCall_i"].apply(null, arguments);
          };
          var dynCall_v = Module["dynCall_v"] = function() {
            return Module["asm"]["dynCall_v"].apply(null, arguments);
          };
          var dynCall_viiiiii = Module["dynCall_viiiiii"] = function() {
            return Module["asm"]["dynCall_viiiiii"].apply(null, arguments);
          };
          var dynCall_viiiii = Module["dynCall_viiiii"] = function() {
            return Module["asm"]["dynCall_viiiii"].apply(null, arguments);
          };
          var dynCall_viiii = Module["dynCall_viiii"] = function() {
            return Module["asm"]["dynCall_viiii"].apply(null, arguments);
          };
          var dynCall_jiji = Module["dynCall_jiji"] = function() {
            return Module["asm"]["dynCall_jiji"].apply(null, arguments);
          };
          Module["asm"] = asm;
          Module["ccall"] = ccall;
          var calledRun;
          Module["then"] = function(func) {
            if (calledRun) {
              func(Module);
            } else {
              var old = Module["onRuntimeInitialized"];
              Module["onRuntimeInitialized"] = function() {
                if (old) old();
                func(Module);
              };
            }
            return Module;
          };
          function ExitStatus(status) {
            this.name = "ExitStatus";
            this.message = "Program terminated with exit(" + status + ")";
            this.status = status;
          }
          dependenciesFulfilled = function runCaller() {
            if (!calledRun) run();
            if (!calledRun) dependenciesFulfilled = runCaller;
          };
          function run(args) {
            args = args || arguments_;
            if (runDependencies > 0) {
              return;
            }
            preRun();
            if (runDependencies > 0) return;
            function doRun() {
              if (calledRun) return;
              calledRun = true;
              if (ABORT) return;
              initRuntime();
              preMain();
              if (Module["onRuntimeInitialized"]) Module["onRuntimeInitialized"]();
              postRun();
            }
            if (Module["setStatus"]) {
              Module["setStatus"]("Running...");
              setTimeout(function() {
                setTimeout(function() {
                  Module["setStatus"]("");
                }, 1);
                doRun();
              }, 1);
            } else {
              doRun();
            }
          }
          Module["run"] = run;
          if (Module["preInit"]) {
            if (typeof Module["preInit"] == "function") Module["preInit"] = [Module["preInit"]];
            while (Module["preInit"].length > 0) {
              Module["preInit"].pop()();
            }
          }
          noExitRuntime = true;
          run();
          return Onigasm2;
        });
      })();
      if (typeof exports === "object" && typeof module === "object")
        module.exports = Onigasm;
      else if (typeof define === "function" && define["amd"])
        define([], function() {
          return Onigasm;
        });
      else if (typeof exports === "object")
        exports["Onigasm"] = Onigasm;
    }
  });

  // node_modules/onigasm/lib/onigasmH.js
  var require_onigasmH = __commonJS({
    "node_modules/onigasm/lib/onigasmH.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var OnigasmModuleFactory = require_onigasm();
      async function initModule(bytes) {
        return new Promise((resolve, reject) => {
          const { log, warn, error } = console;
          OnigasmModuleFactory({
            instantiateWasm(imports, successCallback) {
              WebAssembly.instantiate(bytes, imports).then((output) => {
                successCallback(output.instance);
              }).catch((e) => {
                throw e;
              });
              return {};
            }
          }).then((moduleH) => {
            exports.onigasmH = moduleH;
            resolve();
          });
          if (typeof print !== "undefined") {
            console.log = log;
            console.error = error;
            console.warn = warn;
          }
        });
      }
      var isInitialized = false;
      async function loadWASM(data) {
        if (isInitialized) {
          throw new Error(`Onigasm#init has been called and was succesful, subsequent calls are not allowed once initialized`);
        }
        if (typeof data === "string") {
          const arrayBuffer = await (await fetch(data)).arrayBuffer();
          await initModule(arrayBuffer);
        } else if (data instanceof ArrayBuffer) {
          await initModule(data);
        } else {
          throw new TypeError(`Expected a string (URL of .wasm file) or ArrayBuffer (.wasm file itself) as first parameter`);
        }
        isInitialized = true;
      }
      exports.loadWASM = loadWASM;
    }
  });

  // node_modules/yallist/iterator.js
  var require_iterator = __commonJS({
    "node_modules/yallist/iterator.js"(exports, module) {
      "use strict";
      module.exports = function(Yallist) {
        Yallist.prototype[Symbol.iterator] = function* () {
          for (let walker = this.head; walker; walker = walker.next) {
            yield walker.value;
          }
        };
      };
    }
  });

  // node_modules/yallist/yallist.js
  var require_yallist = __commonJS({
    "node_modules/yallist/yallist.js"(exports, module) {
      "use strict";
      module.exports = Yallist;
      Yallist.Node = Node;
      Yallist.create = Yallist;
      function Yallist(list) {
        var self = this;
        if (!(self instanceof Yallist)) {
          self = new Yallist();
        }
        self.tail = null;
        self.head = null;
        self.length = 0;
        if (list && typeof list.forEach === "function") {
          list.forEach(function(item) {
            self.push(item);
          });
        } else if (arguments.length > 0) {
          for (var i = 0, l = arguments.length; i < l; i++) {
            self.push(arguments[i]);
          }
        }
        return self;
      }
      Yallist.prototype.removeNode = function(node) {
        if (node.list !== this) {
          throw new Error("removing node which does not belong to this list");
        }
        var next = node.next;
        var prev = node.prev;
        if (next) {
          next.prev = prev;
        }
        if (prev) {
          prev.next = next;
        }
        if (node === this.head) {
          this.head = next;
        }
        if (node === this.tail) {
          this.tail = prev;
        }
        node.list.length--;
        node.next = null;
        node.prev = null;
        node.list = null;
        return next;
      };
      Yallist.prototype.unshiftNode = function(node) {
        if (node === this.head) {
          return;
        }
        if (node.list) {
          node.list.removeNode(node);
        }
        var head = this.head;
        node.list = this;
        node.next = head;
        if (head) {
          head.prev = node;
        }
        this.head = node;
        if (!this.tail) {
          this.tail = node;
        }
        this.length++;
      };
      Yallist.prototype.pushNode = function(node) {
        if (node === this.tail) {
          return;
        }
        if (node.list) {
          node.list.removeNode(node);
        }
        var tail = this.tail;
        node.list = this;
        node.prev = tail;
        if (tail) {
          tail.next = node;
        }
        this.tail = node;
        if (!this.head) {
          this.head = node;
        }
        this.length++;
      };
      Yallist.prototype.push = function() {
        for (var i = 0, l = arguments.length; i < l; i++) {
          push(this, arguments[i]);
        }
        return this.length;
      };
      Yallist.prototype.unshift = function() {
        for (var i = 0, l = arguments.length; i < l; i++) {
          unshift(this, arguments[i]);
        }
        return this.length;
      };
      Yallist.prototype.pop = function() {
        if (!this.tail) {
          return void 0;
        }
        var res = this.tail.value;
        this.tail = this.tail.prev;
        if (this.tail) {
          this.tail.next = null;
        } else {
          this.head = null;
        }
        this.length--;
        return res;
      };
      Yallist.prototype.shift = function() {
        if (!this.head) {
          return void 0;
        }
        var res = this.head.value;
        this.head = this.head.next;
        if (this.head) {
          this.head.prev = null;
        } else {
          this.tail = null;
        }
        this.length--;
        return res;
      };
      Yallist.prototype.forEach = function(fn, thisp) {
        thisp = thisp || this;
        for (var walker = this.head, i = 0; walker !== null; i++) {
          fn.call(thisp, walker.value, i, this);
          walker = walker.next;
        }
      };
      Yallist.prototype.forEachReverse = function(fn, thisp) {
        thisp = thisp || this;
        for (var walker = this.tail, i = this.length - 1; walker !== null; i--) {
          fn.call(thisp, walker.value, i, this);
          walker = walker.prev;
        }
      };
      Yallist.prototype.get = function(n) {
        for (var i = 0, walker = this.head; walker !== null && i < n; i++) {
          walker = walker.next;
        }
        if (i === n && walker !== null) {
          return walker.value;
        }
      };
      Yallist.prototype.getReverse = function(n) {
        for (var i = 0, walker = this.tail; walker !== null && i < n; i++) {
          walker = walker.prev;
        }
        if (i === n && walker !== null) {
          return walker.value;
        }
      };
      Yallist.prototype.map = function(fn, thisp) {
        thisp = thisp || this;
        var res = new Yallist();
        for (var walker = this.head; walker !== null; ) {
          res.push(fn.call(thisp, walker.value, this));
          walker = walker.next;
        }
        return res;
      };
      Yallist.prototype.mapReverse = function(fn, thisp) {
        thisp = thisp || this;
        var res = new Yallist();
        for (var walker = this.tail; walker !== null; ) {
          res.push(fn.call(thisp, walker.value, this));
          walker = walker.prev;
        }
        return res;
      };
      Yallist.prototype.reduce = function(fn, initial) {
        var acc;
        var walker = this.head;
        if (arguments.length > 1) {
          acc = initial;
        } else if (this.head) {
          walker = this.head.next;
          acc = this.head.value;
        } else {
          throw new TypeError("Reduce of empty list with no initial value");
        }
        for (var i = 0; walker !== null; i++) {
          acc = fn(acc, walker.value, i);
          walker = walker.next;
        }
        return acc;
      };
      Yallist.prototype.reduceReverse = function(fn, initial) {
        var acc;
        var walker = this.tail;
        if (arguments.length > 1) {
          acc = initial;
        } else if (this.tail) {
          walker = this.tail.prev;
          acc = this.tail.value;
        } else {
          throw new TypeError("Reduce of empty list with no initial value");
        }
        for (var i = this.length - 1; walker !== null; i--) {
          acc = fn(acc, walker.value, i);
          walker = walker.prev;
        }
        return acc;
      };
      Yallist.prototype.toArray = function() {
        var arr = new Array(this.length);
        for (var i = 0, walker = this.head; walker !== null; i++) {
          arr[i] = walker.value;
          walker = walker.next;
        }
        return arr;
      };
      Yallist.prototype.toArrayReverse = function() {
        var arr = new Array(this.length);
        for (var i = 0, walker = this.tail; walker !== null; i++) {
          arr[i] = walker.value;
          walker = walker.prev;
        }
        return arr;
      };
      Yallist.prototype.slice = function(from, to) {
        to = to || this.length;
        if (to < 0) {
          to += this.length;
        }
        from = from || 0;
        if (from < 0) {
          from += this.length;
        }
        var ret = new Yallist();
        if (to < from || to < 0) {
          return ret;
        }
        if (from < 0) {
          from = 0;
        }
        if (to > this.length) {
          to = this.length;
        }
        for (var i = 0, walker = this.head; walker !== null && i < from; i++) {
          walker = walker.next;
        }
        for (; walker !== null && i < to; i++, walker = walker.next) {
          ret.push(walker.value);
        }
        return ret;
      };
      Yallist.prototype.sliceReverse = function(from, to) {
        to = to || this.length;
        if (to < 0) {
          to += this.length;
        }
        from = from || 0;
        if (from < 0) {
          from += this.length;
        }
        var ret = new Yallist();
        if (to < from || to < 0) {
          return ret;
        }
        if (from < 0) {
          from = 0;
        }
        if (to > this.length) {
          to = this.length;
        }
        for (var i = this.length, walker = this.tail; walker !== null && i > to; i--) {
          walker = walker.prev;
        }
        for (; walker !== null && i > from; i--, walker = walker.prev) {
          ret.push(walker.value);
        }
        return ret;
      };
      Yallist.prototype.splice = function(start, deleteCount) {
        if (start > this.length) {
          start = this.length - 1;
        }
        if (start < 0) {
          start = this.length + start;
        }
        for (var i = 0, walker = this.head; walker !== null && i < start; i++) {
          walker = walker.next;
        }
        var ret = [];
        for (var i = 0; walker && i < deleteCount; i++) {
          ret.push(walker.value);
          walker = this.removeNode(walker);
        }
        if (walker === null) {
          walker = this.tail;
        }
        if (walker !== this.head && walker !== this.tail) {
          walker = walker.prev;
        }
        for (var i = 2; i < arguments.length; i++) {
          walker = insert(this, walker, arguments[i]);
        }
        return ret;
      };
      Yallist.prototype.reverse = function() {
        var head = this.head;
        var tail = this.tail;
        for (var walker = head; walker !== null; walker = walker.prev) {
          var p = walker.prev;
          walker.prev = walker.next;
          walker.next = p;
        }
        this.head = tail;
        this.tail = head;
        return this;
      };
      function insert(self, node, value) {
        var inserted = node === self.head ? new Node(value, null, node, self) : new Node(value, node, node.next, self);
        if (inserted.next === null) {
          self.tail = inserted;
        }
        if (inserted.prev === null) {
          self.head = inserted;
        }
        self.length++;
        return inserted;
      }
      function push(self, item) {
        self.tail = new Node(item, self.tail, null, self);
        if (!self.head) {
          self.head = self.tail;
        }
        self.length++;
      }
      function unshift(self, item) {
        self.head = new Node(item, null, self.head, self);
        if (!self.tail) {
          self.tail = self.head;
        }
        self.length++;
      }
      function Node(value, prev, next, list) {
        if (!(this instanceof Node)) {
          return new Node(value, prev, next, list);
        }
        this.list = list;
        this.value = value;
        if (prev) {
          prev.next = this;
          this.prev = prev;
        } else {
          this.prev = null;
        }
        if (next) {
          next.prev = this;
          this.next = next;
        } else {
          this.next = null;
        }
      }
      try {
        require_iterator()(Yallist);
      } catch (er) {
      }
    }
  });

  // node_modules/lru-cache/index.js
  var require_lru_cache = __commonJS({
    "node_modules/lru-cache/index.js"(exports, module) {
      "use strict";
      var Yallist = require_yallist();
      var MAX = /* @__PURE__ */ Symbol("max");
      var LENGTH = /* @__PURE__ */ Symbol("length");
      var LENGTH_CALCULATOR = /* @__PURE__ */ Symbol("lengthCalculator");
      var ALLOW_STALE = /* @__PURE__ */ Symbol("allowStale");
      var MAX_AGE = /* @__PURE__ */ Symbol("maxAge");
      var DISPOSE = /* @__PURE__ */ Symbol("dispose");
      var NO_DISPOSE_ON_SET = /* @__PURE__ */ Symbol("noDisposeOnSet");
      var LRU_LIST = /* @__PURE__ */ Symbol("lruList");
      var CACHE = /* @__PURE__ */ Symbol("cache");
      var UPDATE_AGE_ON_GET = /* @__PURE__ */ Symbol("updateAgeOnGet");
      var naiveLength = () => 1;
      var LRUCache = class {
        constructor(options) {
          if (typeof options === "number")
            options = { max: options };
          if (!options)
            options = {};
          if (options.max && (typeof options.max !== "number" || options.max < 0))
            throw new TypeError("max must be a non-negative number");
          const max = this[MAX] = options.max || Infinity;
          const lc = options.length || naiveLength;
          this[LENGTH_CALCULATOR] = typeof lc !== "function" ? naiveLength : lc;
          this[ALLOW_STALE] = options.stale || false;
          if (options.maxAge && typeof options.maxAge !== "number")
            throw new TypeError("maxAge must be a number");
          this[MAX_AGE] = options.maxAge || 0;
          this[DISPOSE] = options.dispose;
          this[NO_DISPOSE_ON_SET] = options.noDisposeOnSet || false;
          this[UPDATE_AGE_ON_GET] = options.updateAgeOnGet || false;
          this.reset();
        }
        // resize the cache when the max changes.
        set max(mL) {
          if (typeof mL !== "number" || mL < 0)
            throw new TypeError("max must be a non-negative number");
          this[MAX] = mL || Infinity;
          trim(this);
        }
        get max() {
          return this[MAX];
        }
        set allowStale(allowStale) {
          this[ALLOW_STALE] = !!allowStale;
        }
        get allowStale() {
          return this[ALLOW_STALE];
        }
        set maxAge(mA) {
          if (typeof mA !== "number")
            throw new TypeError("maxAge must be a non-negative number");
          this[MAX_AGE] = mA;
          trim(this);
        }
        get maxAge() {
          return this[MAX_AGE];
        }
        // resize the cache when the lengthCalculator changes.
        set lengthCalculator(lC) {
          if (typeof lC !== "function")
            lC = naiveLength;
          if (lC !== this[LENGTH_CALCULATOR]) {
            this[LENGTH_CALCULATOR] = lC;
            this[LENGTH] = 0;
            this[LRU_LIST].forEach((hit) => {
              hit.length = this[LENGTH_CALCULATOR](hit.value, hit.key);
              this[LENGTH] += hit.length;
            });
          }
          trim(this);
        }
        get lengthCalculator() {
          return this[LENGTH_CALCULATOR];
        }
        get length() {
          return this[LENGTH];
        }
        get itemCount() {
          return this[LRU_LIST].length;
        }
        rforEach(fn, thisp) {
          thisp = thisp || this;
          for (let walker = this[LRU_LIST].tail; walker !== null; ) {
            const prev = walker.prev;
            forEachStep(this, fn, walker, thisp);
            walker = prev;
          }
        }
        forEach(fn, thisp) {
          thisp = thisp || this;
          for (let walker = this[LRU_LIST].head; walker !== null; ) {
            const next = walker.next;
            forEachStep(this, fn, walker, thisp);
            walker = next;
          }
        }
        keys() {
          return this[LRU_LIST].toArray().map((k) => k.key);
        }
        values() {
          return this[LRU_LIST].toArray().map((k) => k.value);
        }
        reset() {
          if (this[DISPOSE] && this[LRU_LIST] && this[LRU_LIST].length) {
            this[LRU_LIST].forEach((hit) => this[DISPOSE](hit.key, hit.value));
          }
          this[CACHE] = /* @__PURE__ */ new Map();
          this[LRU_LIST] = new Yallist();
          this[LENGTH] = 0;
        }
        dump() {
          return this[LRU_LIST].map((hit) => isStale(this, hit) ? false : {
            k: hit.key,
            v: hit.value,
            e: hit.now + (hit.maxAge || 0)
          }).toArray().filter((h) => h);
        }
        dumpLru() {
          return this[LRU_LIST];
        }
        set(key, value, maxAge) {
          maxAge = maxAge || this[MAX_AGE];
          if (maxAge && typeof maxAge !== "number")
            throw new TypeError("maxAge must be a number");
          const now = maxAge ? Date.now() : 0;
          const len = this[LENGTH_CALCULATOR](value, key);
          if (this[CACHE].has(key)) {
            if (len > this[MAX]) {
              del(this, this[CACHE].get(key));
              return false;
            }
            const node = this[CACHE].get(key);
            const item = node.value;
            if (this[DISPOSE]) {
              if (!this[NO_DISPOSE_ON_SET])
                this[DISPOSE](key, item.value);
            }
            item.now = now;
            item.maxAge = maxAge;
            item.value = value;
            this[LENGTH] += len - item.length;
            item.length = len;
            this.get(key);
            trim(this);
            return true;
          }
          const hit = new Entry(key, value, len, now, maxAge);
          if (hit.length > this[MAX]) {
            if (this[DISPOSE])
              this[DISPOSE](key, value);
            return false;
          }
          this[LENGTH] += hit.length;
          this[LRU_LIST].unshift(hit);
          this[CACHE].set(key, this[LRU_LIST].head);
          trim(this);
          return true;
        }
        has(key) {
          if (!this[CACHE].has(key)) return false;
          const hit = this[CACHE].get(key).value;
          return !isStale(this, hit);
        }
        get(key) {
          return get(this, key, true);
        }
        peek(key) {
          return get(this, key, false);
        }
        pop() {
          const node = this[LRU_LIST].tail;
          if (!node)
            return null;
          del(this, node);
          return node.value;
        }
        del(key) {
          del(this, this[CACHE].get(key));
        }
        load(arr) {
          this.reset();
          const now = Date.now();
          for (let l = arr.length - 1; l >= 0; l--) {
            const hit = arr[l];
            const expiresAt = hit.e || 0;
            if (expiresAt === 0)
              this.set(hit.k, hit.v);
            else {
              const maxAge = expiresAt - now;
              if (maxAge > 0) {
                this.set(hit.k, hit.v, maxAge);
              }
            }
          }
        }
        prune() {
          this[CACHE].forEach((value, key) => get(this, key, false));
        }
      };
      var get = (self, key, doUse) => {
        const node = self[CACHE].get(key);
        if (node) {
          const hit = node.value;
          if (isStale(self, hit)) {
            del(self, node);
            if (!self[ALLOW_STALE])
              return void 0;
          } else {
            if (doUse) {
              if (self[UPDATE_AGE_ON_GET])
                node.value.now = Date.now();
              self[LRU_LIST].unshiftNode(node);
            }
          }
          return hit.value;
        }
      };
      var isStale = (self, hit) => {
        if (!hit || !hit.maxAge && !self[MAX_AGE])
          return false;
        const diff = Date.now() - hit.now;
        return hit.maxAge ? diff > hit.maxAge : self[MAX_AGE] && diff > self[MAX_AGE];
      };
      var trim = (self) => {
        if (self[LENGTH] > self[MAX]) {
          for (let walker = self[LRU_LIST].tail; self[LENGTH] > self[MAX] && walker !== null; ) {
            const prev = walker.prev;
            del(self, walker);
            walker = prev;
          }
        }
      };
      var del = (self, node) => {
        if (node) {
          const hit = node.value;
          if (self[DISPOSE])
            self[DISPOSE](hit.key, hit.value);
          self[LENGTH] -= hit.length;
          self[CACHE].delete(hit.key);
          self[LRU_LIST].removeNode(node);
        }
      };
      var Entry = class {
        constructor(key, value, length, now, maxAge) {
          this.key = key;
          this.value = value;
          this.length = length;
          this.now = now;
          this.maxAge = maxAge || 0;
        }
      };
      var forEachStep = (self, fn, node, thisp) => {
        let hit = node.value;
        if (isStale(self, hit)) {
          del(self, node);
          if (!self[ALLOW_STALE])
            hit = void 0;
        }
        if (hit)
          fn.call(thisp, hit.value, hit.key, self);
      };
      module.exports = LRUCache;
    }
  });

  // node_modules/onigasm/lib/OnigString.js
  var require_OnigString = __commonJS({
    "node_modules/onigasm/lib/OnigString.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var OnigString = class {
        constructor(content) {
          this.substring = (start, end) => {
            return this.source.substring(start, end);
          };
          this.toString = (start, end) => {
            return this.source;
          };
          if (typeof content !== "string") {
            throw new TypeError("Argument must be a string");
          }
          this.source = content;
          this._utf8Bytes = null;
          this._utf8Indexes = null;
        }
        get utf8Bytes() {
          if (!this._utf8Bytes) {
            this.encode();
          }
          return this._utf8Bytes;
        }
        /**
         * Returns `null` if all utf8 offsets match utf-16 offset (content has no multi byte characters)
         */
        get utf8Indexes() {
          if (!this._utf8Bytes) {
            this.encode();
          }
          return this._utf8Indexes;
        }
        get content() {
          return this.source;
        }
        get length() {
          return this.source.length;
        }
        get hasMultiByteCharacters() {
          return this.utf8Indexes !== null;
        }
        convertUtf8OffsetToUtf16(utf8Offset) {
          if (utf8Offset < 0) {
            return 0;
          }
          const utf8Array = this._utf8Bytes;
          if (utf8Offset >= utf8Array.length - 1) {
            return this.source.length;
          }
          const utf8OffsetMap = this.utf8Indexes;
          if (utf8OffsetMap && utf8Offset >= this._mappingTableStartOffset) {
            return findFirstInSorted(utf8OffsetMap, utf8Offset - this._mappingTableStartOffset) + this._mappingTableStartOffset;
          }
          return utf8Offset;
        }
        convertUtf16OffsetToUtf8(utf16Offset) {
          if (utf16Offset < 0) {
            return 0;
          }
          const utf8Array = this._utf8Bytes;
          if (utf16Offset >= this.source.length) {
            return utf8Array.length - 1;
          }
          const utf8OffsetMap = this.utf8Indexes;
          if (utf8OffsetMap && utf16Offset >= this._mappingTableStartOffset) {
            return utf8OffsetMap[utf16Offset - this._mappingTableStartOffset] + this._mappingTableStartOffset;
          }
          return utf16Offset;
        }
        encode() {
          const str = this.source;
          const n = str.length;
          let utf16OffsetToUtf8;
          let utf8Offset = 0;
          let mappingTableStartOffset = 0;
          function createOffsetTable(startOffset) {
            const maxUtf8Len = (n - startOffset) * 3;
            if (maxUtf8Len <= 255) {
              utf16OffsetToUtf8 = new Uint8Array(n - startOffset);
            } else if (maxUtf8Len <= 65535) {
              utf16OffsetToUtf8 = new Uint16Array(n - startOffset);
            } else {
              utf16OffsetToUtf8 = new Uint32Array(n - startOffset);
            }
            mappingTableStartOffset = startOffset;
            utf16OffsetToUtf8[utf8Offset++] = 0;
          }
          const u8view = new Uint8Array(
            n * 3 + 1
            /** null termination character */
          );
          let ptrHead = 0;
          let i = 0;
          while (i < str.length) {
            let codepoint;
            const c = str.charCodeAt(i);
            if (utf16OffsetToUtf8) {
              utf16OffsetToUtf8[utf8Offset++] = ptrHead - mappingTableStartOffset;
            }
            if (c < 55296 || c > 57343) {
              codepoint = c;
            } else if (c >= 56320) {
              codepoint = 65533;
            } else {
              if (i === n - 1) {
                codepoint = 65533;
              } else {
                const d = str.charCodeAt(i + 1);
                if (56320 <= d && d <= 57343) {
                  if (!utf16OffsetToUtf8) {
                    createOffsetTable(i);
                  }
                  const a = c & 1023;
                  const b = d & 1023;
                  codepoint = 65536 + (a << 10) + b;
                  i += 1;
                  utf16OffsetToUtf8[utf8Offset++] = ptrHead - mappingTableStartOffset;
                } else {
                  codepoint = 65533;
                }
              }
            }
            let bytesRequiredToEncode;
            let offset;
            if (codepoint <= 127) {
              bytesRequiredToEncode = 1;
              offset = 0;
            } else if (codepoint <= 2047) {
              bytesRequiredToEncode = 2;
              offset = 192;
            } else if (codepoint <= 65535) {
              bytesRequiredToEncode = 3;
              offset = 224;
            } else {
              bytesRequiredToEncode = 4;
              offset = 240;
            }
            if (bytesRequiredToEncode === 1) {
              u8view[ptrHead++] = codepoint;
            } else {
              if (!utf16OffsetToUtf8) {
                createOffsetTable(ptrHead);
              }
              u8view[ptrHead++] = (codepoint >> 6 * --bytesRequiredToEncode) + offset;
              while (bytesRequiredToEncode > 0) {
                const temp = codepoint >> 6 * (bytesRequiredToEncode - 1);
                u8view[ptrHead++] = 128 | temp & 63;
                bytesRequiredToEncode -= 1;
              }
            }
            i += 1;
          }
          const utf8 = u8view.slice(0, ptrHead + 1);
          utf8[ptrHead] = 0;
          this._utf8Bytes = utf8;
          if (utf16OffsetToUtf8) {
            this._utf8Indexes = utf16OffsetToUtf8;
            this._mappingTableStartOffset = mappingTableStartOffset;
          }
        }
      };
      function findFirstInSorted(array, i) {
        let low = 0;
        let high = array.length;
        if (high === 0) {
          return 0;
        }
        while (low < high) {
          const mid = Math.floor((low + high) / 2);
          if (array[mid] >= i) {
            high = mid;
          } else {
            low = mid + 1;
          }
        }
        while (low > 0 && (low >= array.length || array[low] > i)) {
          low--;
        }
        if (low > 0 && array[low] === array[low - 1]) {
          low--;
        }
        return low;
      }
      exports.default = OnigString;
    }
  });

  // node_modules/onigasm/lib/OnigScanner.js
  var require_OnigScanner = __commonJS({
    "node_modules/onigasm/lib/OnigScanner.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var LRUCache = require_lru_cache();
      var onigasmH_1 = require_onigasmH();
      var OnigString_1 = require_OnigString();
      function mallocAndWriteString(str) {
        const ptr = onigasmH_1.onigasmH._malloc(str.utf8Bytes.length);
        onigasmH_1.onigasmH.HEAPU8.set(str.utf8Bytes, ptr);
        return ptr;
      }
      function convertUTF8BytesFromPtrToString(ptr) {
        const chars = [];
        let i = 0;
        while (onigasmH_1.onigasmH.HEAPU8[ptr] !== 0) {
          chars[i++] = onigasmH_1.onigasmH.HEAPU8[ptr++];
        }
        return chars.join();
      }
      var cache = new LRUCache({
        dispose: (scanner, info) => {
          const regexTPtrsPtr = onigasmH_1.onigasmH._malloc(info.regexTPtrs.length);
          onigasmH_1.onigasmH.HEAPU8.set(info.regexTPtrs, regexTPtrsPtr);
          const status = onigasmH_1.onigasmH._disposeCompiledPatterns(regexTPtrsPtr, scanner.patterns.length);
          if (status !== 0) {
            const errMessage = convertUTF8BytesFromPtrToString(onigasmH_1.onigasmH._getLastError());
            throw new Error(errMessage);
          }
          onigasmH_1.onigasmH._free(regexTPtrsPtr);
        },
        max: 1e3
      });
      var OnigScanner = class {
        /**
         * Create a new scanner with the given patterns
         * @param patterns  An array of string patterns
         */
        constructor(patterns) {
          if (onigasmH_1.onigasmH === null) {
            throw new Error(`Onigasm has not been initialized, call loadWASM from 'onigasm' exports before using any other API`);
          }
          for (let i = 0; i < patterns.length; i++) {
            const pattern = patterns[i];
            if (typeof pattern !== "string") {
              throw new TypeError(`First parameter to OnigScanner constructor must be array of (pattern) strings`);
            }
          }
          this.sources = patterns.slice();
        }
        get patterns() {
          return this.sources.slice();
        }
        /**
         * Find the next match from a given position
         * @param string The string to search
         * @param startPosition The optional position to start at, defaults to 0
         * @param callback The (error, match) function to call when done, match will null when there is no match
         */
        findNextMatch(string, startPosition, callback) {
          if (startPosition == null) {
            startPosition = 0;
          }
          if (typeof startPosition === "function") {
            callback = startPosition;
            startPosition = 0;
          }
          try {
            const match = this.findNextMatchSync(string, startPosition);
            callback(null, match);
          } catch (error) {
            callback(error);
          }
        }
        /**
         * Find the next match from a given position
         * @param string The string to search
         * @param startPosition The optional position to start at, defaults to 0
         */
        findNextMatchSync(string, startPosition) {
          if (startPosition == null) {
            startPosition = 0;
          }
          startPosition = this.convertToNumber(startPosition);
          let onigNativeInfo = cache.get(this);
          let status = 0;
          if (!onigNativeInfo) {
            const regexTAddrRecieverPtr = onigasmH_1.onigasmH._malloc(4);
            const regexTPtrs = [];
            for (let i = 0; i < this.sources.length; i++) {
              const pattern = this.sources[i];
              const patternStrPtr = mallocAndWriteString(new OnigString_1.default(pattern));
              status = onigasmH_1.onigasmH._compilePattern(patternStrPtr, regexTAddrRecieverPtr);
              if (status !== 0) {
                const errMessage = convertUTF8BytesFromPtrToString(onigasmH_1.onigasmH._getLastError());
                throw new Error(errMessage);
              }
              const regexTAddress = onigasmH_1.onigasmH.HEAP32[regexTAddrRecieverPtr / 4];
              regexTPtrs.push(regexTAddress);
              onigasmH_1.onigasmH._free(patternStrPtr);
            }
            onigNativeInfo = {
              regexTPtrs: new Uint8Array(Uint32Array.from(regexTPtrs).buffer)
            };
            onigasmH_1.onigasmH._free(regexTAddrRecieverPtr);
            cache.set(this, onigNativeInfo);
          }
          const onigString = string instanceof OnigString_1.default ? string : new OnigString_1.default(this.convertToString(string));
          const strPtr = mallocAndWriteString(onigString);
          const resultInfoReceiverPtr = onigasmH_1.onigasmH._malloc(8);
          const regexTPtrsPtr = onigasmH_1.onigasmH._malloc(onigNativeInfo.regexTPtrs.length);
          onigasmH_1.onigasmH.HEAPU8.set(onigNativeInfo.regexTPtrs, regexTPtrsPtr);
          status = onigasmH_1.onigasmH._findBestMatch(
            // regex_t **patterns
            regexTPtrsPtr,
            // int patternCount
            this.sources.length,
            // UChar *utf8String
            strPtr,
            // int strLen
            onigString.utf8Bytes.length - 1,
            // int startOffset
            onigString.convertUtf16OffsetToUtf8(startPosition),
            // int *resultInfo
            resultInfoReceiverPtr
          );
          if (status !== 0) {
            const errMessage = convertUTF8BytesFromPtrToString(onigasmH_1.onigasmH._getLastError());
            throw new Error(errMessage);
          }
          const [
            // The index of pattern which matched the string at least offset from 0 (start)
            bestPatternIdx,
            // Begin address of capture info encoded as pairs
            // like [start, end, start, end, start, end, ...]
            //  - first start-end pair is entire match (index 0 and 1)
            //  - subsequent pairs are capture groups (2, 3 = first capture group, 4, 5 = second capture group and so on)
            encodedResultBeginAddress,
            // Length of the [start, end, ...] sequence so we know how much memory to read (will always be 0 or multiple of 2)
            encodedResultLength
          ] = new Uint32Array(onigasmH_1.onigasmH.HEAPU32.buffer, resultInfoReceiverPtr, 3);
          onigasmH_1.onigasmH._free(strPtr);
          onigasmH_1.onigasmH._free(resultInfoReceiverPtr);
          onigasmH_1.onigasmH._free(regexTPtrsPtr);
          if (encodedResultLength > 0) {
            const encodedResult = new Uint32Array(onigasmH_1.onigasmH.HEAPU32.buffer, encodedResultBeginAddress, encodedResultLength);
            const captureIndices = [];
            let i = 0;
            let captureIdx = 0;
            while (i < encodedResultLength) {
              const index = captureIdx++;
              let start = encodedResult[i++];
              let end = encodedResult[i++];
              if (onigString.hasMultiByteCharacters) {
                start = onigString.convertUtf8OffsetToUtf16(start);
                end = onigString.convertUtf8OffsetToUtf16(end);
              }
              captureIndices.push({
                end,
                index,
                length: end - start,
                start
              });
            }
            onigasmH_1.onigasmH._free(encodedResultBeginAddress);
            return {
              captureIndices,
              index: bestPatternIdx,
              scanner: this
            };
          }
          return null;
        }
        convertToString(value) {
          if (value === void 0) {
            return "undefined";
          }
          if (value === null) {
            return "null";
          }
          if (value instanceof OnigString_1.default) {
            return value.content;
          }
          return value.toString();
        }
        convertToNumber(value) {
          value = parseInt(value, 10);
          if (!isFinite(value)) {
            value = 0;
          }
          value = Math.max(value, 0);
          return value;
        }
      };
      exports.OnigScanner = OnigScanner;
      exports.default = OnigScanner;
    }
  });

  // node_modules/onigasm/lib/OnigRegExp.js
  var require_OnigRegExp = __commonJS({
    "node_modules/onigasm/lib/OnigRegExp.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var OnigScanner_1 = require_OnigScanner();
      var OnigRegExp = class {
        /**
         * Create a new regex with the given pattern
         * @param source A string pattern
         */
        constructor(source) {
          this.source = source;
          try {
            this.scanner = new OnigScanner_1.default([this.source]);
          } catch (error) {
          }
        }
        /**
         * Synchronously search the string for a match starting at the given position
         * @param string The string to search
         * @param startPosition The optional position to start the search at, defaults to `0`
         */
        searchSync(string, startPosition) {
          let match;
          if (startPosition == null) {
            startPosition = 0;
          }
          match = this.scanner.findNextMatchSync(string, startPosition);
          return this.captureIndicesForMatch(string, match);
        }
        /**
         * Search the string for a match starting at the given position
         * @param string The string to search
         * @param startPosition The optional position to start the search at, defaults to `0`
         * @param callback The `(error, match)` function to call when done, match will be null if no matches were found. match will be an array of objects for each matched group on a successful search
         */
        search(string, startPosition, callback) {
          if (startPosition == null) {
            startPosition = 0;
          }
          if (typeof startPosition === "function") {
            callback = startPosition;
            startPosition = 0;
          }
          try {
            const ret = this.searchSync(string, startPosition);
            callback(null, ret);
          } catch (error) {
            callback(error);
          }
        }
        /**
         * Synchronously test if this regular expression matches the given string
         * @param string The string to test against
         */
        testSync(string) {
          if (typeof this.source === "boolean" || typeof string === "boolean") {
            return this.source === string;
          }
          return this.searchSync(string) != null;
        }
        /**
         * Test if this regular expression matches the given string
         * @param string The string to test against
         * @param callback The (error, matches) function to call when done, matches will be true if at least one match is found, false otherwise
         */
        test(string, callback) {
          if (typeof callback !== "function") {
            callback = () => {
            };
          }
          try {
            callback(null, this.testSync(string));
          } catch (error) {
            callback(error);
          }
        }
        captureIndicesForMatch(string, match) {
          if (match != null) {
            const { captureIndices } = match;
            let capture;
            string = this.scanner.convertToString(string);
            for (let i = 0; i < captureIndices.length; i++) {
              capture = captureIndices[i];
              capture.match = string.slice(capture.start, capture.end);
            }
            return captureIndices;
          } else {
            return null;
          }
        }
      };
      exports.default = OnigRegExp;
    }
  });

  // node_modules/onigasm/lib/index.js
  var require_lib = __commonJS({
    "node_modules/onigasm/lib/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var onigasmH_1 = require_onigasmH();
      exports.loadWASM = onigasmH_1.loadWASM;
      var OnigRegExp_1 = require_OnigRegExp();
      exports.OnigRegExp = OnigRegExp_1.default;
      var OnigScanner_1 = require_OnigScanner();
      exports.OnigScanner = OnigScanner_1.default;
      var OnigString_1 = require_OnigString();
      exports.OnigString = OnigString_1.default;
    }
  });

  // node_modules/monaco-textmate/dist/utils.js
  var require_utils = __commonJS({
    "node_modules/monaco-textmate/dist/utils.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      function clone(something) {
        return doClone(something);
      }
      exports.clone = clone;
      function doClone(something) {
        if (Array.isArray(something)) {
          return cloneArray(something);
        }
        if (typeof something === "object") {
          return cloneObj(something);
        }
        return something;
      }
      function cloneArray(arr) {
        var r = [];
        for (var i = 0, len = arr.length; i < len; i++) {
          r[i] = doClone(arr[i]);
        }
        return r;
      }
      function cloneObj(obj) {
        var r = {};
        for (var key in obj) {
          r[key] = doClone(obj[key]);
        }
        return r;
      }
      function mergeObjects(target) {
        var sources = [];
        for (var _i = 1; _i < arguments.length; _i++) {
          sources[_i - 1] = arguments[_i];
        }
        sources.forEach(function(source) {
          for (var key in source) {
            target[key] = source[key];
          }
        });
        return target;
      }
      exports.mergeObjects = mergeObjects;
      var CAPTURING_REGEX_SOURCE = /\$(\d+)|\${(\d+):\/(downcase|upcase)}/;
      var RegexSource = (
        /** @class */
        (function() {
          function RegexSource2() {
          }
          RegexSource2.hasCaptures = function(regexSource) {
            return CAPTURING_REGEX_SOURCE.test(regexSource);
          };
          RegexSource2.replaceCaptures = function(regexSource, captureSource, captureIndices) {
            return regexSource.replace(CAPTURING_REGEX_SOURCE, function(match, index, commandIndex, command) {
              var capture = captureIndices[parseInt(index || commandIndex, 10)];
              if (capture) {
                var result = captureSource.substring(capture.start, capture.end);
                while (result[0] === ".") {
                  result = result.substring(1);
                }
                switch (command) {
                  case "downcase":
                    return result.toLowerCase();
                  case "upcase":
                    return result.toUpperCase();
                  default:
                    return result;
                }
              } else {
                return match;
              }
            });
          };
          return RegexSource2;
        })()
      );
      exports.RegexSource = RegexSource;
    }
  });

  // path-shim.js
  var require_path_shim = __commonJS({
    "path-shim.js"(exports, module) {
      function join() {
        var parts = Array.prototype.filter.call(arguments, function(p) {
          return p && typeof p === "string";
        });
        return parts.join("/").replace(/\/{2,}/g, "/");
      }
      function dirname(p) {
        p = String(p);
        var i = p.lastIndexOf("/");
        return i < 0 ? "." : i === 0 ? "/" : p.slice(0, i);
      }
      function basename(p, ext) {
        p = String(p);
        var b = p.slice(p.lastIndexOf("/") + 1);
        if (ext && b.slice(-ext.length) === ext) {
          b = b.slice(0, -ext.length);
        }
        return b;
      }
      function extname(p) {
        var b = basename(String(p));
        var i = b.lastIndexOf(".");
        return i > 0 ? b.slice(i) : "";
      }
      function normalize(p) {
        return String(p).replace(/\/{2,}/g, "/");
      }
      module.exports = { join, dirname, basename, extname, normalize, sep: "/", posix: null };
    }
  });

  // node_modules/monaco-textmate/dist/rule.js
  var require_rule = __commonJS({
    "node_modules/monaco-textmate/dist/rule.js"(exports) {
      "use strict";
      var __extends = exports && exports.__extends || (function() {
        var extendStatics = Object.setPrototypeOf || { __proto__: [] } instanceof Array && function(d, b) {
          d.__proto__ = b;
        } || function(d, b) {
          for (var p in b) if (b.hasOwnProperty(p)) d[p] = b[p];
        };
        return function(d, b) {
          extendStatics(d, b);
          function __() {
            this.constructor = d;
          }
          d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
        };
      })();
      Object.defineProperty(exports, "__esModule", { value: true });
      var path = require_path_shim();
      var utils_1 = require_utils();
      var onigasm_1 = require_lib();
      var HAS_BACK_REFERENCES = /\\(\d+)/;
      var BACK_REFERENCING_END = /\\(\d+)/g;
      var Rule = (
        /** @class */
        (function() {
          function Rule2($location, id, name, contentName) {
            this.$location = $location;
            this.id = id;
            this._name = name || null;
            this._nameIsCapturing = utils_1.RegexSource.hasCaptures(this._name);
            this._contentName = contentName || null;
            this._contentNameIsCapturing = utils_1.RegexSource.hasCaptures(this._contentName);
          }
          Object.defineProperty(Rule2.prototype, "debugName", {
            get: function() {
              return this.constructor.name + "#" + this.id + " @ " + path.basename(this.$location.filename) + ":" + this.$location.line;
            },
            enumerable: true,
            configurable: true
          });
          Rule2.prototype.getName = function(lineText, captureIndices) {
            if (!this._nameIsCapturing) {
              return this._name;
            }
            return utils_1.RegexSource.replaceCaptures(this._name, lineText, captureIndices);
          };
          Rule2.prototype.getContentName = function(lineText, captureIndices) {
            if (!this._contentNameIsCapturing) {
              return this._contentName;
            }
            return utils_1.RegexSource.replaceCaptures(this._contentName, lineText, captureIndices);
          };
          Rule2.prototype.collectPatternsRecursive = function(grammar, out, isFirst) {
            throw new Error("Implement me!");
          };
          Rule2.prototype.compile = function(grammar, endRegexSource, allowA, allowG) {
            throw new Error("Implement me!");
          };
          return Rule2;
        })()
      );
      exports.Rule = Rule;
      var CaptureRule = (
        /** @class */
        (function(_super) {
          __extends(CaptureRule2, _super);
          function CaptureRule2($location, id, name, contentName, retokenizeCapturedWithRuleId) {
            var _this = _super.call(this, $location, id, name, contentName) || this;
            _this.retokenizeCapturedWithRuleId = retokenizeCapturedWithRuleId;
            return _this;
          }
          return CaptureRule2;
        })(Rule)
      );
      exports.CaptureRule = CaptureRule;
      var RegExpSource = (
        /** @class */
        (function() {
          function RegExpSource2(regExpSource, ruleId, handleAnchors) {
            if (handleAnchors === void 0) {
              handleAnchors = true;
            }
            if (handleAnchors) {
              this._handleAnchors(regExpSource);
            } else {
              this.source = regExpSource;
              this.hasAnchor = false;
            }
            if (this.hasAnchor) {
              this._anchorCache = this._buildAnchorCache();
            }
            this.ruleId = ruleId;
            this.hasBackReferences = HAS_BACK_REFERENCES.test(this.source);
          }
          RegExpSource2.prototype.clone = function() {
            return new RegExpSource2(this.source, this.ruleId, true);
          };
          RegExpSource2.prototype.setSource = function(newSource) {
            if (this.source === newSource) {
              return;
            }
            this.source = newSource;
            if (this.hasAnchor) {
              this._anchorCache = this._buildAnchorCache();
            }
          };
          RegExpSource2.prototype._handleAnchors = function(regExpSource) {
            if (regExpSource) {
              var pos = void 0, len = void 0, ch = void 0, nextCh = void 0, lastPushedPos = 0, output = [];
              var hasAnchor = false;
              for (pos = 0, len = regExpSource.length; pos < len; pos++) {
                ch = regExpSource.charAt(pos);
                if (ch === "\\") {
                  if (pos + 1 < len) {
                    nextCh = regExpSource.charAt(pos + 1);
                    if (nextCh === "z") {
                      output.push(regExpSource.substring(lastPushedPos, pos));
                      output.push("$(?!\\n)(?<!\\n)");
                      lastPushedPos = pos + 2;
                    } else if (nextCh === "A" || nextCh === "G") {
                      hasAnchor = true;
                    }
                    pos++;
                  }
                }
              }
              this.hasAnchor = hasAnchor;
              if (lastPushedPos === 0) {
                this.source = regExpSource;
              } else {
                output.push(regExpSource.substring(lastPushedPos, len));
                this.source = output.join("");
              }
            } else {
              this.hasAnchor = false;
              this.source = regExpSource;
            }
          };
          RegExpSource2.prototype.resolveBackReferences = function(lineText, captureIndices) {
            var capturedValues = captureIndices.map(function(capture) {
              return lineText.substring(capture.start, capture.end);
            });
            BACK_REFERENCING_END.lastIndex = 0;
            return this.source.replace(BACK_REFERENCING_END, function(match, g1) {
              return escapeRegExpCharacters(capturedValues[parseInt(g1, 10)] || "");
            });
          };
          RegExpSource2.prototype._buildAnchorCache = function() {
            var A0_G0_result = [];
            var A0_G1_result = [];
            var A1_G0_result = [];
            var A1_G1_result = [];
            var pos, len, ch, nextCh;
            for (pos = 0, len = this.source.length; pos < len; pos++) {
              ch = this.source.charAt(pos);
              A0_G0_result[pos] = ch;
              A0_G1_result[pos] = ch;
              A1_G0_result[pos] = ch;
              A1_G1_result[pos] = ch;
              if (ch === "\\") {
                if (pos + 1 < len) {
                  nextCh = this.source.charAt(pos + 1);
                  if (nextCh === "A") {
                    A0_G0_result[pos + 1] = "\uFFFF";
                    A0_G1_result[pos + 1] = "\uFFFF";
                    A1_G0_result[pos + 1] = "A";
                    A1_G1_result[pos + 1] = "A";
                  } else if (nextCh === "G") {
                    A0_G0_result[pos + 1] = "\uFFFF";
                    A0_G1_result[pos + 1] = "G";
                    A1_G0_result[pos + 1] = "\uFFFF";
                    A1_G1_result[pos + 1] = "G";
                  } else {
                    A0_G0_result[pos + 1] = nextCh;
                    A0_G1_result[pos + 1] = nextCh;
                    A1_G0_result[pos + 1] = nextCh;
                    A1_G1_result[pos + 1] = nextCh;
                  }
                  pos++;
                }
              }
            }
            return {
              A0_G0: A0_G0_result.join(""),
              A0_G1: A0_G1_result.join(""),
              A1_G0: A1_G0_result.join(""),
              A1_G1: A1_G1_result.join("")
            };
          };
          RegExpSource2.prototype.resolveAnchors = function(allowA, allowG) {
            if (!this.hasAnchor) {
              return this.source;
            }
            if (allowA) {
              if (allowG) {
                return this._anchorCache.A1_G1;
              } else {
                return this._anchorCache.A1_G0;
              }
            } else {
              if (allowG) {
                return this._anchorCache.A0_G1;
              } else {
                return this._anchorCache.A0_G0;
              }
            }
          };
          return RegExpSource2;
        })()
      );
      exports.RegExpSource = RegExpSource;
      function createOnigScanner(sources) {
        return new onigasm_1.OnigScanner(sources);
      }
      function createOnigString(sources) {
        var r = new onigasm_1.OnigString(sources);
        r.$str = sources;
        return r;
      }
      exports.createOnigString = createOnigString;
      function getString(str) {
        return str.$str;
      }
      exports.getString = getString;
      var RegExpSourceList = (
        /** @class */
        (function() {
          function RegExpSourceList2() {
            this._items = [];
            this._hasAnchors = false;
            this._cached = null;
            this._cachedSources = null;
            this._anchorCache = {
              A0_G0: null,
              A0_G1: null,
              A1_G0: null,
              A1_G1: null
            };
          }
          RegExpSourceList2.prototype.push = function(item) {
            this._items.push(item);
            this._hasAnchors = this._hasAnchors || item.hasAnchor;
          };
          RegExpSourceList2.prototype.unshift = function(item) {
            this._items.unshift(item);
            this._hasAnchors = this._hasAnchors || item.hasAnchor;
          };
          RegExpSourceList2.prototype.length = function() {
            return this._items.length;
          };
          RegExpSourceList2.prototype.setSource = function(index, newSource) {
            if (this._items[index].source !== newSource) {
              this._cached = null;
              this._anchorCache.A0_G0 = null;
              this._anchorCache.A0_G1 = null;
              this._anchorCache.A1_G0 = null;
              this._anchorCache.A1_G1 = null;
              this._items[index].setSource(newSource);
            }
          };
          RegExpSourceList2.prototype.compile = function(grammar, allowA, allowG) {
            if (!this._hasAnchors) {
              if (!this._cached) {
                var regExps = this._items.map(function(e) {
                  return e.source;
                });
                this._cached = {
                  scanner: createOnigScanner(regExps),
                  rules: this._items.map(function(e) {
                    return e.ruleId;
                  }),
                  debugRegExps: regExps
                };
              }
              return this._cached;
            } else {
              this._anchorCache = {
                A0_G0: this._anchorCache.A0_G0 || (allowA === false && allowG === false ? this._resolveAnchors(allowA, allowG) : null),
                A0_G1: this._anchorCache.A0_G1 || (allowA === false && allowG === true ? this._resolveAnchors(allowA, allowG) : null),
                A1_G0: this._anchorCache.A1_G0 || (allowA === true && allowG === false ? this._resolveAnchors(allowA, allowG) : null),
                A1_G1: this._anchorCache.A1_G1 || (allowA === true && allowG === true ? this._resolveAnchors(allowA, allowG) : null)
              };
              if (allowA) {
                if (allowG) {
                  return this._anchorCache.A1_G1;
                } else {
                  return this._anchorCache.A1_G0;
                }
              } else {
                if (allowG) {
                  return this._anchorCache.A0_G1;
                } else {
                  return this._anchorCache.A0_G0;
                }
              }
            }
          };
          RegExpSourceList2.prototype._resolveAnchors = function(allowA, allowG) {
            var regExps = this._items.map(function(e) {
              return e.resolveAnchors(allowA, allowG);
            });
            return {
              scanner: createOnigScanner(regExps),
              rules: this._items.map(function(e) {
                return e.ruleId;
              }),
              debugRegExps: regExps
            };
          };
          return RegExpSourceList2;
        })()
      );
      exports.RegExpSourceList = RegExpSourceList;
      var MatchRule = (
        /** @class */
        (function(_super) {
          __extends(MatchRule2, _super);
          function MatchRule2($location, id, name, match, captures) {
            var _this = _super.call(this, $location, id, name, null) || this;
            _this._match = new RegExpSource(match, _this.id);
            _this.captures = captures;
            _this._cachedCompiledPatterns = null;
            return _this;
          }
          Object.defineProperty(MatchRule2.prototype, "debugMatchRegExp", {
            get: function() {
              return "" + this._match.source;
            },
            enumerable: true,
            configurable: true
          });
          MatchRule2.prototype.collectPatternsRecursive = function(grammar, out, isFirst) {
            out.push(this._match);
          };
          MatchRule2.prototype.compile = function(grammar, endRegexSource, allowA, allowG) {
            if (!this._cachedCompiledPatterns) {
              this._cachedCompiledPatterns = new RegExpSourceList();
              this.collectPatternsRecursive(grammar, this._cachedCompiledPatterns, true);
            }
            return this._cachedCompiledPatterns.compile(grammar, allowA, allowG);
          };
          return MatchRule2;
        })(Rule)
      );
      exports.MatchRule = MatchRule;
      var IncludeOnlyRule = (
        /** @class */
        (function(_super) {
          __extends(IncludeOnlyRule2, _super);
          function IncludeOnlyRule2($location, id, name, contentName, patterns) {
            var _this = _super.call(this, $location, id, name, contentName) || this;
            _this.patterns = patterns.patterns;
            _this.hasMissingPatterns = patterns.hasMissingPatterns;
            _this._cachedCompiledPatterns = null;
            return _this;
          }
          IncludeOnlyRule2.prototype.collectPatternsRecursive = function(grammar, out, isFirst) {
            var i, len, rule;
            for (i = 0, len = this.patterns.length; i < len; i++) {
              rule = grammar.getRule(this.patterns[i]);
              rule.collectPatternsRecursive(grammar, out, false);
            }
          };
          IncludeOnlyRule2.prototype.compile = function(grammar, endRegexSource, allowA, allowG) {
            if (!this._cachedCompiledPatterns) {
              this._cachedCompiledPatterns = new RegExpSourceList();
              this.collectPatternsRecursive(grammar, this._cachedCompiledPatterns, true);
            }
            return this._cachedCompiledPatterns.compile(grammar, allowA, allowG);
          };
          return IncludeOnlyRule2;
        })(Rule)
      );
      exports.IncludeOnlyRule = IncludeOnlyRule;
      function escapeRegExpCharacters(value) {
        return value.replace(/[\-\\\{\}\*\+\?\|\^\$\.\,\[\]\(\)\#\s]/g, "\\$&");
      }
      var BeginEndRule = (
        /** @class */
        (function(_super) {
          __extends(BeginEndRule2, _super);
          function BeginEndRule2($location, id, name, contentName, begin, beginCaptures, end, endCaptures, applyEndPatternLast, patterns) {
            var _this = _super.call(this, $location, id, name, contentName) || this;
            _this._begin = new RegExpSource(begin, _this.id);
            _this.beginCaptures = beginCaptures;
            _this._end = new RegExpSource(end, -1);
            _this.endHasBackReferences = _this._end.hasBackReferences;
            _this.endCaptures = endCaptures;
            _this.applyEndPatternLast = applyEndPatternLast || false;
            _this.patterns = patterns.patterns;
            _this.hasMissingPatterns = patterns.hasMissingPatterns;
            _this._cachedCompiledPatterns = null;
            return _this;
          }
          Object.defineProperty(BeginEndRule2.prototype, "debugBeginRegExp", {
            get: function() {
              return "" + this._begin.source;
            },
            enumerable: true,
            configurable: true
          });
          Object.defineProperty(BeginEndRule2.prototype, "debugEndRegExp", {
            get: function() {
              return "" + this._end.source;
            },
            enumerable: true,
            configurable: true
          });
          BeginEndRule2.prototype.getEndWithResolvedBackReferences = function(lineText, captureIndices) {
            return this._end.resolveBackReferences(lineText, captureIndices);
          };
          BeginEndRule2.prototype.collectPatternsRecursive = function(grammar, out, isFirst) {
            if (isFirst) {
              var i = void 0, len = void 0, rule = void 0;
              for (i = 0, len = this.patterns.length; i < len; i++) {
                rule = grammar.getRule(this.patterns[i]);
                rule.collectPatternsRecursive(grammar, out, false);
              }
            } else {
              out.push(this._begin);
            }
          };
          BeginEndRule2.prototype.compile = function(grammar, endRegexSource, allowA, allowG) {
            var precompiled = this._precompile(grammar);
            if (this._end.hasBackReferences) {
              if (this.applyEndPatternLast) {
                precompiled.setSource(precompiled.length() - 1, endRegexSource);
              } else {
                precompiled.setSource(0, endRegexSource);
              }
            }
            return this._cachedCompiledPatterns.compile(grammar, allowA, allowG);
          };
          BeginEndRule2.prototype._precompile = function(grammar) {
            if (!this._cachedCompiledPatterns) {
              this._cachedCompiledPatterns = new RegExpSourceList();
              this.collectPatternsRecursive(grammar, this._cachedCompiledPatterns, true);
              if (this.applyEndPatternLast) {
                this._cachedCompiledPatterns.push(this._end.hasBackReferences ? this._end.clone() : this._end);
              } else {
                this._cachedCompiledPatterns.unshift(this._end.hasBackReferences ? this._end.clone() : this._end);
              }
            }
            return this._cachedCompiledPatterns;
          };
          return BeginEndRule2;
        })(Rule)
      );
      exports.BeginEndRule = BeginEndRule;
      var BeginWhileRule = (
        /** @class */
        (function(_super) {
          __extends(BeginWhileRule2, _super);
          function BeginWhileRule2($location, id, name, contentName, begin, beginCaptures, _while, whileCaptures, patterns) {
            var _this = _super.call(this, $location, id, name, contentName) || this;
            _this._begin = new RegExpSource(begin, _this.id);
            _this.beginCaptures = beginCaptures;
            _this.whileCaptures = whileCaptures;
            _this._while = new RegExpSource(_while, -2);
            _this.whileHasBackReferences = _this._while.hasBackReferences;
            _this.patterns = patterns.patterns;
            _this.hasMissingPatterns = patterns.hasMissingPatterns;
            _this._cachedCompiledPatterns = null;
            _this._cachedCompiledWhilePatterns = null;
            return _this;
          }
          BeginWhileRule2.prototype.getWhileWithResolvedBackReferences = function(lineText, captureIndices) {
            return this._while.resolveBackReferences(lineText, captureIndices);
          };
          BeginWhileRule2.prototype.collectPatternsRecursive = function(grammar, out, isFirst) {
            if (isFirst) {
              var i = void 0, len = void 0, rule = void 0;
              for (i = 0, len = this.patterns.length; i < len; i++) {
                rule = grammar.getRule(this.patterns[i]);
                rule.collectPatternsRecursive(grammar, out, false);
              }
            } else {
              out.push(this._begin);
            }
          };
          BeginWhileRule2.prototype.compile = function(grammar, endRegexSource, allowA, allowG) {
            this._precompile(grammar);
            return this._cachedCompiledPatterns.compile(grammar, allowA, allowG);
          };
          BeginWhileRule2.prototype._precompile = function(grammar) {
            if (!this._cachedCompiledPatterns) {
              this._cachedCompiledPatterns = new RegExpSourceList();
              this.collectPatternsRecursive(grammar, this._cachedCompiledPatterns, true);
            }
          };
          BeginWhileRule2.prototype.compileWhile = function(grammar, endRegexSource, allowA, allowG) {
            this._precompileWhile(grammar);
            if (this._while.hasBackReferences) {
              this._cachedCompiledWhilePatterns.setSource(0, endRegexSource);
            }
            return this._cachedCompiledWhilePatterns.compile(grammar, allowA, allowG);
          };
          BeginWhileRule2.prototype._precompileWhile = function(grammar) {
            if (!this._cachedCompiledWhilePatterns) {
              this._cachedCompiledWhilePatterns = new RegExpSourceList();
              this._cachedCompiledWhilePatterns.push(this._while.hasBackReferences ? this._while.clone() : this._while);
            }
          };
          return BeginWhileRule2;
        })(Rule)
      );
      exports.BeginWhileRule = BeginWhileRule;
      var RuleFactory = (
        /** @class */
        (function() {
          function RuleFactory2() {
          }
          RuleFactory2.createCaptureRule = function(helper, $location, name, contentName, retokenizeCapturedWithRuleId) {
            return helper.registerRule(function(id) {
              return new CaptureRule($location, id, name, contentName, retokenizeCapturedWithRuleId);
            });
          };
          RuleFactory2.getCompiledRuleId = function(desc, helper, repository) {
            if (!desc.id) {
              helper.registerRule(function(id) {
                desc.id = id;
                if (desc.match) {
                  return new MatchRule(desc.$vscodeTextmateLocation, desc.id, desc.name, desc.match, RuleFactory2._compileCaptures(desc.captures, helper, repository));
                }
                if (!desc.begin) {
                  if (desc.repository) {
                    repository = utils_1.mergeObjects({}, repository, desc.repository);
                  }
                  return new IncludeOnlyRule(desc.$vscodeTextmateLocation, desc.id, desc.name, desc.contentName, RuleFactory2._compilePatterns(desc.patterns, helper, repository));
                }
                if (desc.while) {
                  return new BeginWhileRule(desc.$vscodeTextmateLocation, desc.id, desc.name, desc.contentName, desc.begin, RuleFactory2._compileCaptures(desc.beginCaptures || desc.captures, helper, repository), desc.while, RuleFactory2._compileCaptures(desc.whileCaptures || desc.captures, helper, repository), RuleFactory2._compilePatterns(desc.patterns, helper, repository));
                }
                return new BeginEndRule(desc.$vscodeTextmateLocation, desc.id, desc.name, desc.contentName, desc.begin, RuleFactory2._compileCaptures(desc.beginCaptures || desc.captures, helper, repository), desc.end, RuleFactory2._compileCaptures(desc.endCaptures || desc.captures, helper, repository), desc.applyEndPatternLast, RuleFactory2._compilePatterns(desc.patterns, helper, repository));
              });
            }
            return desc.id;
          };
          RuleFactory2._compileCaptures = function(captures, helper, repository) {
            var r = [], numericCaptureId, maximumCaptureId, i, captureId;
            if (captures) {
              maximumCaptureId = 0;
              for (captureId in captures) {
                if (captureId === "$vscodeTextmateLocation") {
                  continue;
                }
                numericCaptureId = parseInt(captureId, 10);
                if (numericCaptureId > maximumCaptureId) {
                  maximumCaptureId = numericCaptureId;
                }
              }
              for (i = 0; i <= maximumCaptureId; i++) {
                r[i] = null;
              }
              for (captureId in captures) {
                if (captureId === "$vscodeTextmateLocation") {
                  continue;
                }
                numericCaptureId = parseInt(captureId, 10);
                var retokenizeCapturedWithRuleId = 0;
                if (captures[captureId].patterns) {
                  retokenizeCapturedWithRuleId = RuleFactory2.getCompiledRuleId(captures[captureId], helper, repository);
                }
                r[numericCaptureId] = RuleFactory2.createCaptureRule(helper, captures[captureId].$vscodeTextmateLocation, captures[captureId].name, captures[captureId].contentName, retokenizeCapturedWithRuleId);
              }
            }
            return r;
          };
          RuleFactory2._compilePatterns = function(patterns, helper, repository) {
            var r = [], pattern, i, len, patternId, externalGrammar, rule, skipRule;
            if (patterns) {
              for (i = 0, len = patterns.length; i < len; i++) {
                pattern = patterns[i];
                patternId = -1;
                if (pattern.include) {
                  if (pattern.include.charAt(0) === "#") {
                    var localIncludedRule = repository[pattern.include.substr(1)];
                    if (localIncludedRule) {
                      patternId = RuleFactory2.getCompiledRuleId(localIncludedRule, helper, repository);
                    } else {
                    }
                  } else if (pattern.include === "$base" || pattern.include === "$self") {
                    patternId = RuleFactory2.getCompiledRuleId(repository[pattern.include], helper, repository);
                  } else {
                    var externalGrammarName = null, externalGrammarInclude = null, sharpIndex = pattern.include.indexOf("#");
                    if (sharpIndex >= 0) {
                      externalGrammarName = pattern.include.substring(0, sharpIndex);
                      externalGrammarInclude = pattern.include.substring(sharpIndex + 1);
                    } else {
                      externalGrammarName = pattern.include;
                    }
                    externalGrammar = helper.getExternalGrammar(externalGrammarName, repository);
                    if (externalGrammar) {
                      if (externalGrammarInclude) {
                        var externalIncludedRule = externalGrammar.repository[externalGrammarInclude];
                        if (externalIncludedRule) {
                          patternId = RuleFactory2.getCompiledRuleId(externalIncludedRule, helper, externalGrammar.repository);
                        } else {
                        }
                      } else {
                        patternId = RuleFactory2.getCompiledRuleId(externalGrammar.repository.$self, helper, externalGrammar.repository);
                      }
                    } else {
                    }
                  }
                } else {
                  patternId = RuleFactory2.getCompiledRuleId(pattern, helper, repository);
                }
                if (patternId !== -1) {
                  rule = helper.getRule(patternId);
                  skipRule = false;
                  if (rule instanceof IncludeOnlyRule || rule instanceof BeginEndRule || rule instanceof BeginWhileRule) {
                    if (rule.hasMissingPatterns && rule.patterns.length === 0) {
                      skipRule = true;
                    }
                  }
                  if (skipRule) {
                    continue;
                  }
                  r.push(patternId);
                }
              }
            }
            return {
              patterns: r,
              hasMissingPatterns: (patterns ? patterns.length : 0) !== r.length
            };
          };
          return RuleFactory2;
        })()
      );
      exports.RuleFactory = RuleFactory;
    }
  });

  // node_modules/monaco-textmate/dist/matcher.js
  var require_matcher = __commonJS({
    "node_modules/monaco-textmate/dist/matcher.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      function createMatchers(selector, matchesName) {
        var results = [];
        var tokenizer = newTokenizer(selector);
        var token = tokenizer.next();
        while (token !== null) {
          var priority = 0;
          if (token.length === 2 && token.charAt(1) === ":") {
            switch (token.charAt(0)) {
              case "R":
                priority = 1;
                break;
              case "L":
                priority = -1;
                break;
              default:
                console.log("Unknown priority " + token + " in scope selector");
            }
            token = tokenizer.next();
          }
          var matcher = parseConjunction();
          if (matcher) {
            results.push({ matcher, priority });
          }
          if (token !== ",") {
            break;
          }
          token = tokenizer.next();
        }
        return results;
        function parseOperand() {
          if (token === "-") {
            token = tokenizer.next();
            var expressionToNegate = parseOperand();
            return function(matcherInput) {
              return expressionToNegate && !expressionToNegate(matcherInput);
            };
          }
          if (token === "(") {
            token = tokenizer.next();
            var expressionInParents = parseInnerExpression();
            if (token === ")") {
              token = tokenizer.next();
            }
            return expressionInParents;
          }
          if (isIdentifier(token)) {
            var identifiers = [];
            do {
              identifiers.push(token);
              token = tokenizer.next();
            } while (isIdentifier(token));
            return function(matcherInput) {
              return matchesName(identifiers, matcherInput);
            };
          }
          return null;
        }
        function parseConjunction() {
          var matchers = [];
          var matcher2 = parseOperand();
          while (matcher2) {
            matchers.push(matcher2);
            matcher2 = parseOperand();
          }
          return function(matcherInput) {
            return matchers.every(function(matcher3) {
              return matcher3(matcherInput);
            });
          };
        }
        function parseInnerExpression() {
          var matchers = [];
          var matcher2 = parseConjunction();
          while (matcher2) {
            matchers.push(matcher2);
            if (token === "|" || token === ",") {
              do {
                token = tokenizer.next();
              } while (token === "|" || token === ",");
            } else {
              break;
            }
            matcher2 = parseConjunction();
          }
          return function(matcherInput) {
            return matchers.some(function(matcher3) {
              return matcher3(matcherInput);
            });
          };
        }
      }
      exports.createMatchers = createMatchers;
      function isIdentifier(token) {
        return token && token.match(/[\w\.:]+/);
      }
      function newTokenizer(input) {
        var regex = /([LR]:|[\w\.:][\w\.:\-]*|[\,\|\-\(\)])/g;
        var match = regex.exec(input);
        return {
          next: function() {
            if (!match) {
              return null;
            }
            var res = match[0];
            match = regex.exec(input);
            return res;
          }
        };
      }
    }
  });

  // node_modules/monaco-textmate/dist/debug.js
  var require_debug = __commonJS({
    "node_modules/monaco-textmate/dist/debug.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.CAPTURE_METADATA = typeof process === "undefined" ? false : !!process.env["VSCODE_TEXTMATE_DEBUG"];
      exports.IN_DEBUG_MODE = typeof process === "undefined" ? false : !!process.env["VSCODE_TEXTMATE_DEBUG"];
    }
  });

  // node_modules/monaco-textmate/dist/grammar.js
  var require_grammar = __commonJS({
    "node_modules/monaco-textmate/dist/grammar.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var utils_1 = require_utils();
      var rule_1 = require_rule();
      var matcher_1 = require_matcher();
      var debug_1 = require_debug();
      function createGrammar(grammar, initialLanguage, embeddedLanguages, tokenTypes, grammarRepository) {
        return new Grammar(grammar, initialLanguage, embeddedLanguages, tokenTypes, grammarRepository);
      }
      exports.createGrammar = createGrammar;
      function _extractIncludedScopesInPatterns(result, patterns) {
        for (var i = 0, len = patterns.length; i < len; i++) {
          if (Array.isArray(patterns[i].patterns)) {
            _extractIncludedScopesInPatterns(result, patterns[i].patterns);
          }
          var include = patterns[i].include;
          if (!include) {
            continue;
          }
          if (include === "$base" || include === "$self") {
            continue;
          }
          if (include.charAt(0) === "#") {
            continue;
          }
          var sharpIndex = include.indexOf("#");
          if (sharpIndex >= 0) {
            result[include.substring(0, sharpIndex)] = true;
          } else {
            result[include] = true;
          }
        }
      }
      function _extractIncludedScopesInRepository(result, repository) {
        for (var name in repository) {
          var rule = repository[name];
          if (rule.patterns && Array.isArray(rule.patterns)) {
            _extractIncludedScopesInPatterns(result, rule.patterns);
          }
          if (rule.repository) {
            _extractIncludedScopesInRepository(result, rule.repository);
          }
        }
      }
      function collectIncludedScopes(result, grammar) {
        if (grammar.patterns && Array.isArray(grammar.patterns)) {
          _extractIncludedScopesInPatterns(result, grammar.patterns);
        }
        if (grammar.repository) {
          _extractIncludedScopesInRepository(result, grammar.repository);
        }
        delete result[grammar.scopeName];
      }
      exports.collectIncludedScopes = collectIncludedScopes;
      function scopesAreMatching(thisScopeName, scopeName) {
        if (!thisScopeName) {
          return false;
        }
        if (thisScopeName === scopeName) {
          return true;
        }
        var len = scopeName.length;
        return thisScopeName.length > len && thisScopeName.substr(0, len) === scopeName && thisScopeName[len] === ".";
      }
      function nameMatcher(identifers, scopes) {
        if (scopes.length < identifers.length) {
          return false;
        }
        var lastIndex = 0;
        return identifers.every(function(identifier) {
          for (var i = lastIndex; i < scopes.length; i++) {
            if (scopesAreMatching(scopes[i], identifier)) {
              lastIndex = i + 1;
              return true;
            }
          }
          return false;
        });
      }
      function collectInjections(result, selector, rule, ruleFactoryHelper, grammar) {
        var matchers = matcher_1.createMatchers(selector, nameMatcher);
        var ruleId = rule_1.RuleFactory.getCompiledRuleId(rule, ruleFactoryHelper, grammar.repository);
        for (var _i = 0, matchers_1 = matchers; _i < matchers_1.length; _i++) {
          var matcher = matchers_1[_i];
          result.push({
            matcher: matcher.matcher,
            ruleId,
            grammar,
            priority: matcher.priority
          });
        }
      }
      var ScopeMetadata = (
        /** @class */
        /* @__PURE__ */ (function() {
          function ScopeMetadata2(scopeName, languageId, tokenType, themeData) {
            this.scopeName = scopeName;
            this.languageId = languageId;
            this.tokenType = tokenType;
            this.themeData = themeData;
          }
          return ScopeMetadata2;
        })()
      );
      exports.ScopeMetadata = ScopeMetadata;
      var ScopeMetadataProvider = (
        /** @class */
        (function() {
          function ScopeMetadataProvider2(initialLanguage, themeProvider, embeddedLanguages) {
            this._initialLanguage = initialLanguage;
            this._themeProvider = themeProvider;
            this.onDidChangeTheme();
            this._embeddedLanguages = /* @__PURE__ */ Object.create(null);
            if (embeddedLanguages) {
              var scopes = Object.keys(embeddedLanguages);
              for (var i = 0, len = scopes.length; i < len; i++) {
                var scope = scopes[i];
                var language = embeddedLanguages[scope];
                if (typeof language !== "number" || language === 0) {
                  console.warn("Invalid embedded language found at scope " + scope + ": <<" + language + ">>");
                  continue;
                }
                this._embeddedLanguages[scope] = language;
              }
            }
            var escapedScopes = Object.keys(this._embeddedLanguages).map(function(scopeName) {
              return ScopeMetadataProvider2._escapeRegExpCharacters(scopeName);
            });
            if (escapedScopes.length === 0) {
              this._embeddedLanguagesRegex = null;
            } else {
              escapedScopes.sort();
              escapedScopes.reverse();
              this._embeddedLanguagesRegex = new RegExp("^((" + escapedScopes.join(")|(") + "))($|\\.)", "");
            }
          }
          ScopeMetadataProvider2.prototype.onDidChangeTheme = function() {
            this._cache = /* @__PURE__ */ Object.create(null);
            this._defaultMetaData = new ScopeMetadata("", this._initialLanguage, 0, [this._themeProvider.getDefaults()]);
          };
          ScopeMetadataProvider2.prototype.getDefaultMetadata = function() {
            return this._defaultMetaData;
          };
          ScopeMetadataProvider2._escapeRegExpCharacters = function(value) {
            return value.replace(/[\-\\\{\}\*\+\?\|\^\$\.\,\[\]\(\)\#\s]/g, "\\$&");
          };
          ScopeMetadataProvider2.prototype.getMetadataForScope = function(scopeName) {
            if (scopeName === null) {
              return ScopeMetadataProvider2._NULL_SCOPE_METADATA;
            }
            var value = this._cache[scopeName];
            if (value) {
              return value;
            }
            value = this._doGetMetadataForScope(scopeName);
            this._cache[scopeName] = value;
            return value;
          };
          ScopeMetadataProvider2.prototype._doGetMetadataForScope = function(scopeName) {
            var languageId = this._scopeToLanguage(scopeName);
            var standardTokenType = this._toStandardTokenType(scopeName);
            var themeData = this._themeProvider.themeMatch(scopeName);
            return new ScopeMetadata(scopeName, languageId, standardTokenType, themeData);
          };
          ScopeMetadataProvider2.prototype._scopeToLanguage = function(scope) {
            if (!scope) {
              return 0;
            }
            if (!this._embeddedLanguagesRegex) {
              return 0;
            }
            var m = scope.match(this._embeddedLanguagesRegex);
            if (!m) {
              return 0;
            }
            var language = this._embeddedLanguages[m[1]] || 0;
            if (!language) {
              return 0;
            }
            return language;
          };
          ScopeMetadataProvider2.prototype._toStandardTokenType = function(tokenType) {
            var m = tokenType.match(ScopeMetadataProvider2.STANDARD_TOKEN_TYPE_REGEXP);
            if (!m) {
              return 0;
            }
            switch (m[1]) {
              case "comment":
                return 1;
              case "string":
                return 2;
              case "regex":
                return 4;
              case "meta.embedded":
                return 8;
            }
            throw new Error("Unexpected match for standard token type!");
          };
          ScopeMetadataProvider2._NULL_SCOPE_METADATA = new ScopeMetadata("", 0, 0, null);
          ScopeMetadataProvider2.STANDARD_TOKEN_TYPE_REGEXP = /\b(comment|string|regex|meta\.embedded)\b/;
          return ScopeMetadataProvider2;
        })()
      );
      var Grammar = (
        /** @class */
        (function() {
          function Grammar2(grammar, initialLanguage, embeddedLanguages, tokenTypes, grammarRepository) {
            this._scopeMetadataProvider = new ScopeMetadataProvider(initialLanguage, grammarRepository, embeddedLanguages);
            this._rootId = -1;
            this._lastRuleId = 0;
            this._ruleId2desc = [];
            this._includedGrammars = {};
            this._grammarRepository = grammarRepository;
            this._grammar = initGrammar(grammar, null);
            this._tokenTypeMatchers = [];
            if (tokenTypes) {
              for (var _i = 0, _a = Object.keys(tokenTypes); _i < _a.length; _i++) {
                var selector = _a[_i];
                var matchers = matcher_1.createMatchers(selector, nameMatcher);
                for (var _b = 0, matchers_2 = matchers; _b < matchers_2.length; _b++) {
                  var matcher = matchers_2[_b];
                  this._tokenTypeMatchers.push({
                    matcher: matcher.matcher,
                    type: tokenTypes[selector]
                  });
                }
              }
            }
          }
          Grammar2.prototype.onDidChangeTheme = function() {
            this._scopeMetadataProvider.onDidChangeTheme();
          };
          Grammar2.prototype.getMetadataForScope = function(scope) {
            return this._scopeMetadataProvider.getMetadataForScope(scope);
          };
          Grammar2.prototype.getInjections = function() {
            var _this = this;
            if (!this._injections) {
              this._injections = [];
              var rawInjections = this._grammar.injections;
              if (rawInjections) {
                for (var expression in rawInjections) {
                  collectInjections(this._injections, expression, rawInjections[expression], this, this._grammar);
                }
              }
              if (this._grammarRepository) {
                var injectionScopeNames = this._grammarRepository.injections(this._grammar.scopeName);
                if (injectionScopeNames) {
                  injectionScopeNames.forEach(function(injectionScopeName) {
                    var injectionGrammar = _this.getExternalGrammar(injectionScopeName);
                    if (injectionGrammar) {
                      var selector = injectionGrammar.injectionSelector;
                      if (selector) {
                        collectInjections(_this._injections, selector, injectionGrammar, _this, injectionGrammar);
                      }
                    }
                  });
                }
              }
              this._injections.sort(function(i1, i2) {
                return i1.priority - i2.priority;
              });
            }
            if (this._injections.length === 0) {
              return this._injections;
            }
            return this._injections;
          };
          Grammar2.prototype.registerRule = function(factory) {
            var id = ++this._lastRuleId;
            var result = factory(id);
            this._ruleId2desc[id] = result;
            return result;
          };
          Grammar2.prototype.getRule = function(patternId) {
            return this._ruleId2desc[patternId];
          };
          Grammar2.prototype.getExternalGrammar = function(scopeName, repository) {
            if (this._includedGrammars[scopeName]) {
              return this._includedGrammars[scopeName];
            } else if (this._grammarRepository) {
              var rawIncludedGrammar = this._grammarRepository.lookup(scopeName);
              if (rawIncludedGrammar) {
                this._includedGrammars[scopeName] = initGrammar(rawIncludedGrammar, repository && repository.$base);
                return this._includedGrammars[scopeName];
              }
            }
          };
          Grammar2.prototype.tokenizeLine = function(lineText, prevState) {
            var r = this._tokenize(lineText, prevState, false);
            return {
              tokens: r.lineTokens.getResult(r.ruleStack, r.lineLength),
              ruleStack: r.ruleStack
            };
          };
          Grammar2.prototype.tokenizeLine2 = function(lineText, prevState) {
            var r = this._tokenize(lineText, prevState, true);
            return {
              tokens: r.lineTokens.getBinaryResult(r.ruleStack, r.lineLength),
              ruleStack: r.ruleStack
            };
          };
          Grammar2.prototype._tokenize = function(lineText, prevState, emitBinaryTokens) {
            if (this._rootId === -1) {
              this._rootId = rule_1.RuleFactory.getCompiledRuleId(this._grammar.repository.$self, this, this._grammar.repository);
            }
            var isFirstLine;
            if (!prevState || prevState === StackElement.NULL) {
              isFirstLine = true;
              var rawDefaultMetadata = this._scopeMetadataProvider.getDefaultMetadata();
              var defaultTheme = rawDefaultMetadata.themeData[0];
              var defaultMetadata = StackElementMetadata.set(0, rawDefaultMetadata.languageId, rawDefaultMetadata.tokenType, defaultTheme.fontStyle, defaultTheme.foreground, defaultTheme.background);
              var rootScopeName = this.getRule(this._rootId).getName(null, null);
              var rawRootMetadata = this._scopeMetadataProvider.getMetadataForScope(rootScopeName);
              var rootMetadata = ScopeListElement.mergeMetadata(defaultMetadata, null, rawRootMetadata);
              var scopeList = new ScopeListElement(null, rootScopeName, rootMetadata);
              prevState = new StackElement(null, this._rootId, -1, null, scopeList, scopeList);
            } else {
              isFirstLine = false;
              prevState.reset();
            }
            lineText = lineText + "\n";
            var onigLineText = rule_1.createOnigString(lineText);
            var lineLength = rule_1.getString(onigLineText).length;
            var lineTokens = new LineTokens(emitBinaryTokens, lineText, this._tokenTypeMatchers);
            var nextState = _tokenizeString(this, onigLineText, isFirstLine, 0, prevState, lineTokens);
            return {
              lineLength,
              lineTokens,
              ruleStack: nextState
            };
          };
          return Grammar2;
        })()
      );
      exports.Grammar = Grammar;
      function initGrammar(grammar, base) {
        grammar = utils_1.clone(grammar);
        grammar.repository = grammar.repository || {};
        grammar.repository.$self = {
          $vscodeTextmateLocation: grammar.$vscodeTextmateLocation,
          patterns: grammar.patterns,
          name: grammar.scopeName
        };
        grammar.repository.$base = base || grammar.repository.$self;
        return grammar;
      }
      function handleCaptures(grammar, lineText, isFirstLine, stack, lineTokens, captures, captureIndices) {
        if (captures.length === 0) {
          return;
        }
        var len = Math.min(captures.length, captureIndices.length);
        var localStack = [];
        var maxEnd = captureIndices[0].end;
        for (var i = 0; i < len; i++) {
          var captureRule = captures[i];
          if (captureRule === null) {
            continue;
          }
          var captureIndex = captureIndices[i];
          if (captureIndex.length === 0) {
            continue;
          }
          if (captureIndex.start > maxEnd) {
            break;
          }
          while (localStack.length > 0 && localStack[localStack.length - 1].endPos <= captureIndex.start) {
            lineTokens.produceFromScopes(localStack[localStack.length - 1].scopes, localStack[localStack.length - 1].endPos);
            localStack.pop();
          }
          if (localStack.length > 0) {
            lineTokens.produceFromScopes(localStack[localStack.length - 1].scopes, captureIndex.start);
          } else {
            lineTokens.produce(stack, captureIndex.start);
          }
          if (captureRule.retokenizeCapturedWithRuleId) {
            var scopeName = captureRule.getName(rule_1.getString(lineText), captureIndices);
            var nameScopesList = stack.contentNameScopesList.push(grammar, scopeName);
            var contentName = captureRule.getContentName(rule_1.getString(lineText), captureIndices);
            var contentNameScopesList = nameScopesList.push(grammar, contentName);
            var stackClone = stack.push(captureRule.retokenizeCapturedWithRuleId, captureIndex.start, null, nameScopesList, contentNameScopesList);
            _tokenizeString(grammar, rule_1.createOnigString(rule_1.getString(lineText).substring(0, captureIndex.end)), isFirstLine && captureIndex.start === 0, captureIndex.start, stackClone, lineTokens);
            continue;
          }
          var captureRuleScopeName = captureRule.getName(rule_1.getString(lineText), captureIndices);
          if (captureRuleScopeName !== null) {
            var base = localStack.length > 0 ? localStack[localStack.length - 1].scopes : stack.contentNameScopesList;
            var captureRuleScopesList = base.push(grammar, captureRuleScopeName);
            localStack.push(new LocalStackElement(captureRuleScopesList, captureIndex.end));
          }
        }
        while (localStack.length > 0) {
          lineTokens.produceFromScopes(localStack[localStack.length - 1].scopes, localStack[localStack.length - 1].endPos);
          localStack.pop();
        }
      }
      function debugCompiledRuleToString(ruleScanner) {
        var r = [];
        for (var i = 0, len = ruleScanner.rules.length; i < len; i++) {
          r.push("   - " + ruleScanner.rules[i] + ": " + ruleScanner.debugRegExps[i]);
        }
        return r.join("\n");
      }
      function matchInjections(injections, grammar, lineText, isFirstLine, linePos, stack, anchorPosition) {
        var bestMatchRating = Number.MAX_VALUE;
        var bestMatchCaptureIndices = null;
        var bestMatchRuleId;
        var bestMatchResultPriority = 0;
        var scopes = stack.contentNameScopesList.generateScopes();
        for (var i = 0, len = injections.length; i < len; i++) {
          var injection = injections[i];
          if (!injection.matcher(scopes)) {
            continue;
          }
          var ruleScanner = grammar.getRule(injection.ruleId).compile(grammar, null, isFirstLine, linePos === anchorPosition);
          var matchResult = ruleScanner.scanner.findNextMatchSync(lineText, linePos);
          if (debug_1.IN_DEBUG_MODE) {
            console.log("  scanning for injections");
            console.log(debugCompiledRuleToString(ruleScanner));
          }
          if (!matchResult) {
            continue;
          }
          var matchRating = matchResult.captureIndices[0].start;
          if (matchRating >= bestMatchRating) {
            continue;
          }
          bestMatchRating = matchRating;
          bestMatchCaptureIndices = matchResult.captureIndices;
          bestMatchRuleId = ruleScanner.rules[matchResult.index];
          bestMatchResultPriority = injection.priority;
          if (bestMatchRating === linePos) {
            break;
          }
        }
        if (bestMatchCaptureIndices) {
          return {
            priorityMatch: bestMatchResultPriority === -1,
            captureIndices: bestMatchCaptureIndices,
            matchedRuleId: bestMatchRuleId
          };
        }
        return null;
      }
      function matchRule(grammar, lineText, isFirstLine, linePos, stack, anchorPosition) {
        var rule = stack.getRule(grammar);
        var ruleScanner = rule.compile(grammar, stack.endRule, isFirstLine, linePos === anchorPosition);
        var r = ruleScanner.scanner.findNextMatchSync(lineText, linePos);
        if (debug_1.IN_DEBUG_MODE) {
          console.log("  scanning for");
          console.log(debugCompiledRuleToString(ruleScanner));
        }
        if (r) {
          return {
            captureIndices: r.captureIndices,
            matchedRuleId: ruleScanner.rules[r.index]
          };
        }
        return null;
      }
      function matchRuleOrInjections(grammar, lineText, isFirstLine, linePos, stack, anchorPosition) {
        var matchResult = matchRule(grammar, lineText, isFirstLine, linePos, stack, anchorPosition);
        var injections = grammar.getInjections();
        if (injections.length === 0) {
          return matchResult;
        }
        var injectionResult = matchInjections(injections, grammar, lineText, isFirstLine, linePos, stack, anchorPosition);
        if (!injectionResult) {
          return matchResult;
        }
        if (!matchResult) {
          return injectionResult;
        }
        var matchResultScore = matchResult.captureIndices[0].start;
        var injectionResultScore = injectionResult.captureIndices[0].start;
        if (injectionResultScore < matchResultScore || injectionResult.priorityMatch && injectionResultScore === matchResultScore) {
          return injectionResult;
        }
        return matchResult;
      }
      function _checkWhileConditions(grammar, lineText, isFirstLine, linePos, stack, lineTokens) {
        var anchorPosition = -1;
        var whileRules = [];
        for (var node = stack; node; node = node.pop()) {
          var nodeRule = node.getRule(grammar);
          if (nodeRule instanceof rule_1.BeginWhileRule) {
            whileRules.push({
              rule: nodeRule,
              stack: node
            });
          }
        }
        for (var whileRule = whileRules.pop(); whileRule; whileRule = whileRules.pop()) {
          var ruleScanner = whileRule.rule.compileWhile(grammar, whileRule.stack.endRule, isFirstLine, anchorPosition === linePos);
          var r = ruleScanner.scanner.findNextMatchSync(lineText, linePos);
          if (debug_1.IN_DEBUG_MODE) {
            console.log("  scanning for while rule");
            console.log(debugCompiledRuleToString(ruleScanner));
          }
          if (r) {
            var matchedRuleId = ruleScanner.rules[r.index];
            if (matchedRuleId !== -2) {
              stack = whileRule.stack.pop();
              break;
            }
            if (r.captureIndices && r.captureIndices.length) {
              lineTokens.produce(whileRule.stack, r.captureIndices[0].start);
              handleCaptures(grammar, lineText, isFirstLine, whileRule.stack, lineTokens, whileRule.rule.whileCaptures, r.captureIndices);
              lineTokens.produce(whileRule.stack, r.captureIndices[0].end);
              anchorPosition = r.captureIndices[0].end;
              if (r.captureIndices[0].end > linePos) {
                linePos = r.captureIndices[0].end;
                isFirstLine = false;
              }
            }
          } else {
            stack = whileRule.stack.pop();
            break;
          }
        }
        return { stack, linePos, anchorPosition, isFirstLine };
      }
      function _tokenizeString(grammar, lineText, isFirstLine, linePos, stack, lineTokens) {
        var lineLength = rule_1.getString(lineText).length;
        var STOP = false;
        var whileCheckResult = _checkWhileConditions(grammar, lineText, isFirstLine, linePos, stack, lineTokens);
        stack = whileCheckResult.stack;
        linePos = whileCheckResult.linePos;
        isFirstLine = whileCheckResult.isFirstLine;
        var anchorPosition = whileCheckResult.anchorPosition;
        while (!STOP) {
          scanNext();
        }
        function scanNext() {
          if (debug_1.IN_DEBUG_MODE) {
            console.log("");
            console.log("@@scanNext: |" + rule_1.getString(lineText).replace(/\n$/, "\\n").substr(linePos) + "|");
          }
          var r = matchRuleOrInjections(grammar, lineText, isFirstLine, linePos, stack, anchorPosition);
          if (!r) {
            if (debug_1.IN_DEBUG_MODE) {
              console.log("  no more matches.");
            }
            lineTokens.produce(stack, lineLength);
            STOP = true;
            return;
          }
          var captureIndices = r.captureIndices;
          var matchedRuleId = r.matchedRuleId;
          var hasAdvanced = captureIndices && captureIndices.length > 0 ? captureIndices[0].end > linePos : false;
          if (matchedRuleId === -1) {
            var poppedRule = stack.getRule(grammar);
            if (debug_1.IN_DEBUG_MODE) {
              console.log("  popping " + poppedRule.debugName + " - " + poppedRule.debugEndRegExp);
            }
            lineTokens.produce(stack, captureIndices[0].start);
            stack = stack.setContentNameScopesList(stack.nameScopesList);
            handleCaptures(grammar, lineText, isFirstLine, stack, lineTokens, poppedRule.endCaptures, captureIndices);
            lineTokens.produce(stack, captureIndices[0].end);
            var popped = stack;
            stack = stack.pop();
            if (!hasAdvanced && popped.getEnterPos() === linePos) {
              console.error("[1] - Grammar is in an endless loop - Grammar pushed & popped a rule without advancing");
              stack = popped;
              lineTokens.produce(stack, lineLength);
              STOP = true;
              return;
            }
          } else {
            var _rule = grammar.getRule(matchedRuleId);
            lineTokens.produce(stack, captureIndices[0].start);
            var beforePush = stack;
            var scopeName = _rule.getName(rule_1.getString(lineText), captureIndices);
            var nameScopesList = stack.contentNameScopesList.push(grammar, scopeName);
            stack = stack.push(matchedRuleId, linePos, null, nameScopesList, nameScopesList);
            if (_rule instanceof rule_1.BeginEndRule) {
              var pushedRule = _rule;
              if (debug_1.IN_DEBUG_MODE) {
                console.log("  pushing " + pushedRule.debugName + " - " + pushedRule.debugBeginRegExp);
              }
              handleCaptures(grammar, lineText, isFirstLine, stack, lineTokens, pushedRule.beginCaptures, captureIndices);
              lineTokens.produce(stack, captureIndices[0].end);
              anchorPosition = captureIndices[0].end;
              var contentName = pushedRule.getContentName(rule_1.getString(lineText), captureIndices);
              var contentNameScopesList = nameScopesList.push(grammar, contentName);
              stack = stack.setContentNameScopesList(contentNameScopesList);
              if (pushedRule.endHasBackReferences) {
                stack = stack.setEndRule(pushedRule.getEndWithResolvedBackReferences(rule_1.getString(lineText), captureIndices));
              }
              if (!hasAdvanced && beforePush.hasSameRuleAs(stack)) {
                console.error("[2] - Grammar is in an endless loop - Grammar pushed the same rule without advancing");
                stack = stack.pop();
                lineTokens.produce(stack, lineLength);
                STOP = true;
                return;
              }
            } else if (_rule instanceof rule_1.BeginWhileRule) {
              var pushedRule = _rule;
              if (debug_1.IN_DEBUG_MODE) {
                console.log("  pushing " + pushedRule.debugName);
              }
              handleCaptures(grammar, lineText, isFirstLine, stack, lineTokens, pushedRule.beginCaptures, captureIndices);
              lineTokens.produce(stack, captureIndices[0].end);
              anchorPosition = captureIndices[0].end;
              var contentName = pushedRule.getContentName(rule_1.getString(lineText), captureIndices);
              var contentNameScopesList = nameScopesList.push(grammar, contentName);
              stack = stack.setContentNameScopesList(contentNameScopesList);
              if (pushedRule.whileHasBackReferences) {
                stack = stack.setEndRule(pushedRule.getWhileWithResolvedBackReferences(rule_1.getString(lineText), captureIndices));
              }
              if (!hasAdvanced && beforePush.hasSameRuleAs(stack)) {
                console.error("[3] - Grammar is in an endless loop - Grammar pushed the same rule without advancing");
                stack = stack.pop();
                lineTokens.produce(stack, lineLength);
                STOP = true;
                return;
              }
            } else {
              var matchingRule = _rule;
              if (debug_1.IN_DEBUG_MODE) {
                console.log("  matched " + matchingRule.debugName + " - " + matchingRule.debugMatchRegExp);
              }
              handleCaptures(grammar, lineText, isFirstLine, stack, lineTokens, matchingRule.captures, captureIndices);
              lineTokens.produce(stack, captureIndices[0].end);
              stack = stack.pop();
              if (!hasAdvanced) {
                console.error("[4] - Grammar is in an endless loop - Grammar is not advancing, nor is it pushing/popping");
                stack = stack.safePop();
                lineTokens.produce(stack, lineLength);
                STOP = true;
                return;
              }
            }
          }
          if (captureIndices[0].end > linePos) {
            linePos = captureIndices[0].end;
            isFirstLine = false;
          }
        }
        return stack;
      }
      var StackElementMetadata = (
        /** @class */
        (function() {
          function StackElementMetadata2() {
          }
          StackElementMetadata2.toBinaryStr = function(metadata) {
            var r = metadata.toString(2);
            while (r.length < 32) {
              r = "0" + r;
            }
            return r;
          };
          StackElementMetadata2.printMetadata = function(metadata) {
            var languageId = StackElementMetadata2.getLanguageId(metadata);
            var tokenType = StackElementMetadata2.getTokenType(metadata);
            var fontStyle = StackElementMetadata2.getFontStyle(metadata);
            var foreground = StackElementMetadata2.getForeground(metadata);
            var background = StackElementMetadata2.getBackground(metadata);
            console.log({
              languageId,
              tokenType,
              fontStyle,
              foreground,
              background
            });
          };
          StackElementMetadata2.getLanguageId = function(metadata) {
            return (metadata & 255) >>> 0;
          };
          StackElementMetadata2.getTokenType = function(metadata) {
            return (metadata & 1792) >>> 8;
          };
          StackElementMetadata2.getFontStyle = function(metadata) {
            return (metadata & 14336) >>> 11;
          };
          StackElementMetadata2.getForeground = function(metadata) {
            return (metadata & 8372224) >>> 14;
          };
          StackElementMetadata2.getBackground = function(metadata) {
            return (metadata & 4286578688) >>> 23;
          };
          StackElementMetadata2.set = function(metadata, languageId, tokenType, fontStyle, foreground, background) {
            var _languageId = StackElementMetadata2.getLanguageId(metadata);
            var _tokenType = StackElementMetadata2.getTokenType(metadata);
            var _fontStyle = StackElementMetadata2.getFontStyle(metadata);
            var _foreground = StackElementMetadata2.getForeground(metadata);
            var _background = StackElementMetadata2.getBackground(metadata);
            if (languageId !== 0) {
              _languageId = languageId;
            }
            if (tokenType !== 0) {
              _tokenType = tokenType === 8 ? 0 : tokenType;
            }
            if (fontStyle !== -1) {
              _fontStyle = fontStyle;
            }
            if (foreground !== 0) {
              _foreground = foreground;
            }
            if (background !== 0) {
              _background = background;
            }
            return (_languageId << 0 | _tokenType << 8 | _fontStyle << 11 | _foreground << 14 | _background << 23) >>> 0;
          };
          return StackElementMetadata2;
        })()
      );
      exports.StackElementMetadata = StackElementMetadata;
      var ScopeListElement = (
        /** @class */
        (function() {
          function ScopeListElement2(parent, scope, metadata) {
            this.parent = parent;
            this.scope = scope;
            this.metadata = metadata;
          }
          ScopeListElement2._equals = function(a, b) {
            do {
              if (a === b) {
                return true;
              }
              if (a.scope !== b.scope || a.metadata !== b.metadata) {
                return false;
              }
              a = a.parent;
              b = b.parent;
              if (!a && !b) {
                return true;
              }
              if (!a || !b) {
                return false;
              }
            } while (true);
          };
          ScopeListElement2.prototype.equals = function(other) {
            return ScopeListElement2._equals(this, other);
          };
          ScopeListElement2._matchesScope = function(scope, selector, selectorWithDot) {
            return selector === scope || scope.substring(0, selectorWithDot.length) === selectorWithDot;
          };
          ScopeListElement2._matches = function(target, parentScopes) {
            if (parentScopes === null) {
              return true;
            }
            var len = parentScopes.length;
            var index = 0;
            var selector = parentScopes[index];
            var selectorWithDot = selector + ".";
            while (target) {
              if (this._matchesScope(target.scope, selector, selectorWithDot)) {
                index++;
                if (index === len) {
                  return true;
                }
                selector = parentScopes[index];
                selectorWithDot = selector + ".";
              }
              target = target.parent;
            }
            return false;
          };
          ScopeListElement2.mergeMetadata = function(metadata, scopesList, source) {
            if (source === null) {
              return metadata;
            }
            var fontStyle = -1;
            var foreground = 0;
            var background = 0;
            if (source.themeData !== null) {
              for (var i = 0, len = source.themeData.length; i < len; i++) {
                var themeData = source.themeData[i];
                if (this._matches(scopesList, themeData.parentScopes)) {
                  fontStyle = themeData.fontStyle;
                  foreground = themeData.foreground;
                  background = themeData.background;
                  break;
                }
              }
            }
            return StackElementMetadata.set(metadata, source.languageId, source.tokenType, fontStyle, foreground, background);
          };
          ScopeListElement2._push = function(target, grammar, scopes) {
            for (var i = 0, len = scopes.length; i < len; i++) {
              var scope = scopes[i];
              var rawMetadata = grammar.getMetadataForScope(scope);
              var metadata = ScopeListElement2.mergeMetadata(target.metadata, target, rawMetadata);
              target = new ScopeListElement2(target, scope, metadata);
            }
            return target;
          };
          ScopeListElement2.prototype.push = function(grammar, scope) {
            if (scope === null) {
              return this;
            }
            if (scope.indexOf(" ") >= 0) {
              return ScopeListElement2._push(this, grammar, scope.split(/ /g));
            }
            return ScopeListElement2._push(this, grammar, [scope]);
          };
          ScopeListElement2._generateScopes = function(scopesList) {
            var result = [], resultLen = 0;
            while (scopesList) {
              result[resultLen++] = scopesList.scope;
              scopesList = scopesList.parent;
            }
            result.reverse();
            return result;
          };
          ScopeListElement2.prototype.generateScopes = function() {
            return ScopeListElement2._generateScopes(this);
          };
          return ScopeListElement2;
        })()
      );
      exports.ScopeListElement = ScopeListElement;
      var StackElement = (
        /** @class */
        (function() {
          function StackElement2(parent, ruleId, enterPos, endRule, nameScopesList, contentNameScopesList) {
            this.parent = parent;
            this.depth = this.parent ? this.parent.depth + 1 : 1;
            this.ruleId = ruleId;
            this._enterPos = enterPos;
            this.endRule = endRule;
            this.nameScopesList = nameScopesList;
            this.contentNameScopesList = contentNameScopesList;
          }
          StackElement2._structuralEquals = function(a, b) {
            do {
              if (a === b) {
                return true;
              }
              if (a.depth !== b.depth || a.ruleId !== b.ruleId || a.endRule !== b.endRule) {
                return false;
              }
              a = a.parent;
              b = b.parent;
              if (!a && !b) {
                return true;
              }
              if (!a || !b) {
                return false;
              }
            } while (true);
          };
          StackElement2._equals = function(a, b) {
            if (a === b) {
              return true;
            }
            if (!this._structuralEquals(a, b)) {
              return false;
            }
            return a.contentNameScopesList.equals(b.contentNameScopesList);
          };
          StackElement2.prototype.clone = function() {
            return this;
          };
          StackElement2.prototype.equals = function(other) {
            if (other === null) {
              return false;
            }
            return StackElement2._equals(this, other);
          };
          StackElement2._reset = function(el) {
            while (el) {
              el._enterPos = -1;
              el = el.parent;
            }
          };
          StackElement2.prototype.reset = function() {
            StackElement2._reset(this);
          };
          StackElement2.prototype.pop = function() {
            return this.parent;
          };
          StackElement2.prototype.safePop = function() {
            if (this.parent) {
              return this.parent;
            }
            return this;
          };
          StackElement2.prototype.push = function(ruleId, enterPos, endRule, nameScopesList, contentNameScopesList) {
            return new StackElement2(this, ruleId, enterPos, endRule, nameScopesList, contentNameScopesList);
          };
          StackElement2.prototype.getEnterPos = function() {
            return this._enterPos;
          };
          StackElement2.prototype.getRule = function(grammar) {
            return grammar.getRule(this.ruleId);
          };
          StackElement2.prototype._writeString = function(res, outIndex) {
            if (this.parent) {
              outIndex = this.parent._writeString(res, outIndex);
            }
            res[outIndex++] = "(" + this.ruleId + ", TODO-" + this.nameScopesList + ", TODO-" + this.contentNameScopesList + ")";
            return outIndex;
          };
          StackElement2.prototype.toString = function() {
            var r = [];
            this._writeString(r, 0);
            return "[" + r.join(",") + "]";
          };
          StackElement2.prototype.setContentNameScopesList = function(contentNameScopesList) {
            if (this.contentNameScopesList === contentNameScopesList) {
              return this;
            }
            return this.parent.push(this.ruleId, this._enterPos, this.endRule, this.nameScopesList, contentNameScopesList);
          };
          StackElement2.prototype.setEndRule = function(endRule) {
            if (this.endRule === endRule) {
              return this;
            }
            return new StackElement2(this.parent, this.ruleId, this._enterPos, endRule, this.nameScopesList, this.contentNameScopesList);
          };
          StackElement2.prototype.hasSameRuleAs = function(other) {
            return this.ruleId === other.ruleId;
          };
          StackElement2.NULL = new StackElement2(null, 0, 0, null, null, null);
          return StackElement2;
        })()
      );
      exports.StackElement = StackElement;
      var LocalStackElement = (
        /** @class */
        /* @__PURE__ */ (function() {
          function LocalStackElement2(scopes, endPos) {
            this.scopes = scopes;
            this.endPos = endPos;
          }
          return LocalStackElement2;
        })()
      );
      exports.LocalStackElement = LocalStackElement;
      var LineTokens = (
        /** @class */
        (function() {
          function LineTokens2(emitBinaryTokens, lineText, tokenTypeOverrides) {
            this._emitBinaryTokens = emitBinaryTokens;
            this._tokenTypeOverrides = tokenTypeOverrides;
            if (debug_1.IN_DEBUG_MODE) {
              this._lineText = lineText;
            }
            if (this._emitBinaryTokens) {
              this._binaryTokens = [];
            } else {
              this._tokens = [];
            }
            this._lastTokenEndIndex = 0;
          }
          LineTokens2.prototype.produce = function(stack, endIndex) {
            this.produceFromScopes(stack.contentNameScopesList, endIndex);
          };
          LineTokens2.prototype.produceFromScopes = function(scopesList, endIndex) {
            if (this._lastTokenEndIndex >= endIndex) {
              return;
            }
            if (this._emitBinaryTokens) {
              var metadata = scopesList.metadata;
              for (var _i = 0, _a = this._tokenTypeOverrides; _i < _a.length; _i++) {
                var tokenType = _a[_i];
                if (tokenType.matcher(scopesList.generateScopes())) {
                  metadata = StackElementMetadata.set(metadata, 0, toTemporaryType(tokenType.type), -1, 0, 0);
                }
              }
              if (this._binaryTokens.length > 0 && this._binaryTokens[this._binaryTokens.length - 1] === metadata) {
                this._lastTokenEndIndex = endIndex;
                return;
              }
              this._binaryTokens.push(this._lastTokenEndIndex);
              this._binaryTokens.push(metadata);
              this._lastTokenEndIndex = endIndex;
              return;
            }
            var scopes = scopesList.generateScopes();
            if (debug_1.IN_DEBUG_MODE) {
              console.log("  token: |" + this._lineText.substring(this._lastTokenEndIndex, endIndex).replace(/\n$/, "\\n") + "|");
              for (var k = 0; k < scopes.length; k++) {
                console.log("      * " + scopes[k]);
              }
            }
            this._tokens.push({
              startIndex: this._lastTokenEndIndex,
              endIndex,
              // value: lineText.substring(lastTokenEndIndex, endIndex),
              scopes
            });
            this._lastTokenEndIndex = endIndex;
          };
          LineTokens2.prototype.getResult = function(stack, lineLength) {
            if (this._tokens.length > 0 && this._tokens[this._tokens.length - 1].startIndex === lineLength - 1) {
              this._tokens.pop();
            }
            if (this._tokens.length === 0) {
              this._lastTokenEndIndex = -1;
              this.produce(stack, lineLength);
              this._tokens[this._tokens.length - 1].startIndex = 0;
            }
            return this._tokens;
          };
          LineTokens2.prototype.getBinaryResult = function(stack, lineLength) {
            if (this._binaryTokens.length > 0 && this._binaryTokens[this._binaryTokens.length - 2] === lineLength - 1) {
              this._binaryTokens.pop();
              this._binaryTokens.pop();
            }
            if (this._binaryTokens.length === 0) {
              this._lastTokenEndIndex = -1;
              this.produce(stack, lineLength);
              this._binaryTokens[this._binaryTokens.length - 2] = 0;
            }
            var result = new Uint32Array(this._binaryTokens.length);
            for (var i = 0, len = this._binaryTokens.length; i < len; i++) {
              result[i] = this._binaryTokens[i];
            }
            return result;
          };
          return LineTokens2;
        })()
      );
      function toTemporaryType(standardType) {
        switch (standardType) {
          case 4:
            return 4;
          case 2:
            return 2;
          case 1:
            return 1;
          case 0:
          default:
            return 8;
        }
      }
    }
  });

  // node_modules/monaco-textmate/dist/registry.js
  var require_registry = __commonJS({
    "node_modules/monaco-textmate/dist/registry.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var grammar_1 = require_grammar();
      var SyncRegistry = (
        /** @class */
        (function() {
          function SyncRegistry2(theme) {
            this._theme = theme;
            this._grammars = {};
            this._rawGrammars = {};
            this._injectionGrammars = {};
          }
          SyncRegistry2.prototype.setTheme = function(theme) {
            var _this = this;
            this._theme = theme;
            Object.keys(this._grammars).forEach(function(scopeName) {
              var grammar = _this._grammars[scopeName];
              grammar.onDidChangeTheme();
            });
          };
          SyncRegistry2.prototype.getColorMap = function() {
            return this._theme.getColorMap();
          };
          SyncRegistry2.prototype.addGrammar = function(grammar, injectionScopeNames) {
            this._rawGrammars[grammar.scopeName] = grammar;
            var includedScopes = {};
            grammar_1.collectIncludedScopes(includedScopes, grammar);
            if (injectionScopeNames) {
              this._injectionGrammars[grammar.scopeName] = injectionScopeNames;
              injectionScopeNames.forEach(function(scopeName) {
                includedScopes[scopeName] = true;
              });
            }
            return Object.keys(includedScopes);
          };
          SyncRegistry2.prototype.lookup = function(scopeName) {
            return this._rawGrammars[scopeName];
          };
          SyncRegistry2.prototype.injections = function(targetScope) {
            return this._injectionGrammars[targetScope];
          };
          SyncRegistry2.prototype.getDefaults = function() {
            return this._theme.getDefaults();
          };
          SyncRegistry2.prototype.themeMatch = function(scopeName) {
            return this._theme.match(scopeName);
          };
          SyncRegistry2.prototype.grammarForScopeName = function(scopeName, initialLanguage, embeddedLanguages, tokenTypes) {
            if (!this._grammars[scopeName]) {
              var rawGrammar = this._rawGrammars[scopeName];
              if (!rawGrammar) {
                return null;
              }
              this._grammars[scopeName] = grammar_1.createGrammar(rawGrammar, initialLanguage, embeddedLanguages, tokenTypes, this);
            }
            return this._grammars[scopeName];
          };
          return SyncRegistry2;
        })()
      );
      exports.SyncRegistry = SyncRegistry;
    }
  });

  // node_modules/fast-plist/release/src/main.js
  var require_main = __commonJS({
    "node_modules/fast-plist/release/src/main.js"(exports) {
      "use strict";
      exports.__esModule = true;
      exports.parse = exports.parseWithLocation = void 0;
      function parseWithLocation(content, filename, locationKeyName) {
        return _parse(content, filename, locationKeyName);
      }
      exports.parseWithLocation = parseWithLocation;
      function parse(content) {
        return _parse(content, null, null);
      }
      exports.parse = parse;
      function _parse(content, filename, locationKeyName) {
        var len = content.length;
        var pos = 0;
        var line = 1;
        var char = 0;
        if (len > 0 && content.charCodeAt(0) === 65279) {
          pos = 1;
        }
        function advancePosBy(by) {
          if (locationKeyName === null) {
            pos = pos + by;
          } else {
            while (by > 0) {
              var chCode2 = content.charCodeAt(pos);
              if (chCode2 === 10) {
                pos++;
                line++;
                char = 0;
              } else {
                pos++;
                char++;
              }
              by--;
            }
          }
        }
        function advancePosTo(to) {
          if (locationKeyName === null) {
            pos = to;
          } else {
            advancePosBy(to - pos);
          }
        }
        function skipWhitespace() {
          while (pos < len) {
            var chCode2 = content.charCodeAt(pos);
            if (chCode2 !== 32 && chCode2 !== 9 && chCode2 !== 13 && chCode2 !== 10) {
              break;
            }
            advancePosBy(1);
          }
        }
        function advanceIfStartsWith(str) {
          if (content.substr(pos, str.length) === str) {
            advancePosBy(str.length);
            return true;
          }
          return false;
        }
        function advanceUntil(str) {
          var nextOccurence = content.indexOf(str, pos);
          if (nextOccurence !== -1) {
            advancePosTo(nextOccurence + str.length);
          } else {
            advancePosTo(len);
          }
        }
        function captureUntil(str) {
          var nextOccurence = content.indexOf(str, pos);
          if (nextOccurence !== -1) {
            var r = content.substring(pos, nextOccurence);
            advancePosTo(nextOccurence + str.length);
            return r;
          } else {
            var r = content.substr(pos);
            advancePosTo(len);
            return r;
          }
        }
        var state = 0;
        var cur = null;
        var stateStack = [];
        var objStack = [];
        var curKey = null;
        function pushState(newState, newCur) {
          stateStack.push(state);
          objStack.push(cur);
          state = newState;
          cur = newCur;
        }
        function popState() {
          if (stateStack.length === 0) {
            return fail("illegal state stack");
          }
          state = stateStack.pop();
          cur = objStack.pop();
        }
        function fail(msg) {
          throw new Error("Near offset " + pos + ": " + msg + " ~~~" + content.substr(pos, 50) + "~~~");
        }
        var dictState = {
          enterDict: function() {
            if (curKey === null) {
              return fail("missing <key>");
            }
            var newDict = {};
            if (locationKeyName !== null) {
              newDict[locationKeyName] = {
                filename,
                line,
                char
              };
            }
            cur[curKey] = newDict;
            curKey = null;
            pushState(1, newDict);
          },
          enterArray: function() {
            if (curKey === null) {
              return fail("missing <key>");
            }
            var newArr = [];
            cur[curKey] = newArr;
            curKey = null;
            pushState(2, newArr);
          }
        };
        var arrState = {
          enterDict: function() {
            var newDict = {};
            if (locationKeyName !== null) {
              newDict[locationKeyName] = {
                filename,
                line,
                char
              };
            }
            cur.push(newDict);
            pushState(1, newDict);
          },
          enterArray: function() {
            var newArr = [];
            cur.push(newArr);
            pushState(2, newArr);
          }
        };
        function enterDict() {
          if (state === 1) {
            dictState.enterDict();
          } else if (state === 2) {
            arrState.enterDict();
          } else {
            cur = {};
            if (locationKeyName !== null) {
              cur[locationKeyName] = {
                filename,
                line,
                char
              };
            }
            pushState(1, cur);
          }
        }
        function leaveDict() {
          if (state === 1) {
            popState();
          } else if (state === 2) {
            return fail("unexpected </dict>");
          } else {
            return fail("unexpected </dict>");
          }
        }
        function enterArray() {
          if (state === 1) {
            dictState.enterArray();
          } else if (state === 2) {
            arrState.enterArray();
          } else {
            cur = [];
            pushState(2, cur);
          }
        }
        function leaveArray() {
          if (state === 1) {
            return fail("unexpected </array>");
          } else if (state === 2) {
            popState();
          } else {
            return fail("unexpected </array>");
          }
        }
        function acceptKey(val) {
          if (state === 1) {
            if (curKey !== null) {
              return fail("too many <key>");
            }
            curKey = val;
          } else if (state === 2) {
            return fail("unexpected <key>");
          } else {
            return fail("unexpected <key>");
          }
        }
        function acceptString(val) {
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function acceptReal(val) {
          if (isNaN(val)) {
            return fail("cannot parse float");
          }
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function acceptInteger(val) {
          if (isNaN(val)) {
            return fail("cannot parse integer");
          }
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function acceptDate(val) {
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function acceptData(val) {
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function acceptBool(val) {
          if (state === 1) {
            if (curKey === null) {
              return fail("missing <key>");
            }
            cur[curKey] = val;
            curKey = null;
          } else if (state === 2) {
            cur.push(val);
          } else {
            cur = val;
          }
        }
        function escapeVal(str) {
          return str.replace(/&#([0-9]+);/g, function(_, m0) {
            return String.fromCodePoint(parseInt(m0, 10));
          }).replace(/&#x([0-9a-f]+);/g, function(_, m0) {
            return String.fromCodePoint(parseInt(m0, 16));
          }).replace(/&amp;|&lt;|&gt;|&quot;|&apos;/g, function(_) {
            switch (_) {
              case "&amp;":
                return "&";
              case "&lt;":
                return "<";
              case "&gt;":
                return ">";
              case "&quot;":
                return '"';
              case "&apos;":
                return "'";
            }
            return _;
          });
        }
        function parseOpenTag() {
          var r = captureUntil(">");
          var isClosed = false;
          if (r.charCodeAt(r.length - 1) === 47) {
            isClosed = true;
            r = r.substring(0, r.length - 1);
          }
          return {
            name: r.trim(),
            isClosed
          };
        }
        function parseTagValue(tag2) {
          if (tag2.isClosed) {
            return "";
          }
          var val = captureUntil("</");
          advanceUntil(">");
          return escapeVal(val);
        }
        while (pos < len) {
          skipWhitespace();
          if (pos >= len) {
            break;
          }
          var chCode = content.charCodeAt(pos);
          advancePosBy(1);
          if (chCode !== 60) {
            return fail("expected <");
          }
          if (pos >= len) {
            return fail("unexpected end of input");
          }
          var peekChCode = content.charCodeAt(pos);
          if (peekChCode === 63) {
            advancePosBy(1);
            advanceUntil("?>");
            continue;
          }
          if (peekChCode === 33) {
            advancePosBy(1);
            if (advanceIfStartsWith("--")) {
              advanceUntil("-->");
              continue;
            }
            advanceUntil(">");
            continue;
          }
          if (peekChCode === 47) {
            advancePosBy(1);
            skipWhitespace();
            if (advanceIfStartsWith("plist")) {
              advanceUntil(">");
              continue;
            }
            if (advanceIfStartsWith("dict")) {
              advanceUntil(">");
              leaveDict();
              continue;
            }
            if (advanceIfStartsWith("array")) {
              advanceUntil(">");
              leaveArray();
              continue;
            }
            return fail("unexpected closed tag");
          }
          var tag = parseOpenTag();
          switch (tag.name) {
            case "dict":
              enterDict();
              if (tag.isClosed) {
                leaveDict();
              }
              continue;
            case "array":
              enterArray();
              if (tag.isClosed) {
                leaveArray();
              }
              continue;
            case "key":
              acceptKey(parseTagValue(tag));
              continue;
            case "string":
              acceptString(parseTagValue(tag));
              continue;
            case "real":
              acceptReal(parseFloat(parseTagValue(tag)));
              continue;
            case "integer":
              acceptInteger(parseInt(parseTagValue(tag), 10));
              continue;
            case "date":
              acceptDate(new Date(parseTagValue(tag)));
              continue;
            case "data":
              acceptData(parseTagValue(tag));
              continue;
            case "true":
              parseTagValue(tag);
              acceptBool(true);
              continue;
            case "false":
              parseTagValue(tag);
              acceptBool(false);
              continue;
          }
          if (/^plist/.test(tag.name)) {
            continue;
          }
          return fail("unexpected opened tag " + tag.name);
        }
        return cur;
      }
    }
  });

  // node_modules/monaco-textmate/dist/json.js
  var require_json = __commonJS({
    "node_modules/monaco-textmate/dist/json.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      function doFail(streamState, msg) {
        throw new Error("Near offset " + streamState.pos + ": " + msg + " ~~~" + streamState.source.substr(streamState.pos, 50) + "~~~");
      }
      function parse(source, filename, withMetadata) {
        var streamState = new JSONStreamState(source);
        var token = new JSONToken();
        var state = 0;
        var cur = null;
        var stateStack = [];
        var objStack = [];
        function pushState() {
          stateStack.push(state);
          objStack.push(cur);
        }
        function popState() {
          state = stateStack.pop();
          cur = objStack.pop();
        }
        function fail(msg) {
          doFail(streamState, msg);
        }
        while (nextJSONToken(streamState, token)) {
          if (state === 0) {
            if (cur !== null) {
              fail("too many constructs in root");
            }
            if (token.type === 3) {
              cur = {};
              if (withMetadata) {
                cur.$vscodeTextmateLocation = token.toLocation(filename);
              }
              pushState();
              state = 1;
              continue;
            }
            if (token.type === 2) {
              cur = [];
              pushState();
              state = 4;
              continue;
            }
            fail("unexpected token in root");
          }
          if (state === 2) {
            if (token.type === 5) {
              popState();
              continue;
            }
            if (token.type === 7) {
              state = 3;
              continue;
            }
            fail("expected , or }");
          }
          if (state === 1 || state === 3) {
            if (state === 1 && token.type === 5) {
              popState();
              continue;
            }
            if (token.type === 1) {
              var keyValue = token.value;
              if (!nextJSONToken(streamState, token) || token.type !== 6) {
                fail("expected colon");
              }
              if (!nextJSONToken(streamState, token)) {
                fail("expected value");
              }
              state = 2;
              if (token.type === 1) {
                cur[keyValue] = token.value;
                continue;
              }
              if (token.type === 8) {
                cur[keyValue] = null;
                continue;
              }
              if (token.type === 9) {
                cur[keyValue] = true;
                continue;
              }
              if (token.type === 10) {
                cur[keyValue] = false;
                continue;
              }
              if (token.type === 11) {
                cur[keyValue] = parseFloat(token.value);
                continue;
              }
              if (token.type === 2) {
                var newArr = [];
                cur[keyValue] = newArr;
                pushState();
                state = 4;
                cur = newArr;
                continue;
              }
              if (token.type === 3) {
                var newDict = {};
                if (withMetadata) {
                  newDict.$vscodeTextmateLocation = token.toLocation(filename);
                }
                cur[keyValue] = newDict;
                pushState();
                state = 1;
                cur = newDict;
                continue;
              }
            }
            fail("unexpected token in dict");
          }
          if (state === 5) {
            if (token.type === 4) {
              popState();
              continue;
            }
            if (token.type === 7) {
              state = 6;
              continue;
            }
            fail("expected , or ]");
          }
          if (state === 4 || state === 6) {
            if (state === 4 && token.type === 4) {
              popState();
              continue;
            }
            state = 5;
            if (token.type === 1) {
              cur.push(token.value);
              continue;
            }
            if (token.type === 8) {
              cur.push(null);
              continue;
            }
            if (token.type === 9) {
              cur.push(true);
              continue;
            }
            if (token.type === 10) {
              cur.push(false);
              continue;
            }
            if (token.type === 11) {
              cur.push(parseFloat(token.value));
              continue;
            }
            if (token.type === 2) {
              var newArr = [];
              cur.push(newArr);
              pushState();
              state = 4;
              cur = newArr;
              continue;
            }
            if (token.type === 3) {
              var newDict = {};
              if (withMetadata) {
                newDict.$vscodeTextmateLocation = token.toLocation(filename);
              }
              cur.push(newDict);
              pushState();
              state = 1;
              cur = newDict;
              continue;
            }
            fail("unexpected token in array");
          }
          fail("unknown state");
        }
        if (objStack.length !== 0) {
          fail("unclosed constructs");
        }
        return cur;
      }
      exports.parse = parse;
      var JSONStreamState = (
        /** @class */
        /* @__PURE__ */ (function() {
          function JSONStreamState2(source) {
            this.source = source;
            this.pos = 0;
            this.len = source.length;
            this.line = 1;
            this.char = 0;
          }
          return JSONStreamState2;
        })()
      );
      var JSONToken = (
        /** @class */
        (function() {
          function JSONToken2() {
            this.value = null;
            this.offset = -1;
            this.len = -1;
            this.line = -1;
            this.char = -1;
          }
          JSONToken2.prototype.toLocation = function(filename) {
            return {
              filename,
              line: this.line,
              char: this.char
            };
          };
          return JSONToken2;
        })()
      );
      function nextJSONToken(_state, _out) {
        _out.value = null;
        _out.type = 0;
        _out.offset = -1;
        _out.len = -1;
        _out.line = -1;
        _out.char = -1;
        var source = _state.source;
        var pos = _state.pos;
        var len = _state.len;
        var line = _state.line;
        var char = _state.char;
        var chCode;
        do {
          if (pos >= len) {
            return false;
          }
          chCode = source.charCodeAt(pos);
          if (chCode === 32 || chCode === 9 || chCode === 13) {
            pos++;
            char++;
            continue;
          }
          if (chCode === 10) {
            pos++;
            line++;
            char = 0;
            continue;
          }
          break;
        } while (true);
        _out.offset = pos;
        _out.line = line;
        _out.char = char;
        if (chCode === 34) {
          _out.type = 1;
          pos++;
          char++;
          do {
            if (pos >= len) {
              return false;
            }
            chCode = source.charCodeAt(pos);
            pos++;
            char++;
            if (chCode === 92) {
              pos++;
              char++;
              continue;
            }
            if (chCode === 34) {
              break;
            }
          } while (true);
          _out.value = source.substring(_out.offset + 1, pos - 1).replace(/\\u([0-9A-Fa-f]{4})/g, function(_, m0) {
            return String.fromCodePoint(parseInt(m0, 16));
          }).replace(/\\(.)/g, function(_, m0) {
            switch (m0) {
              case '"':
                return '"';
              case "\\":
                return "\\";
              case "/":
                return "/";
              case "b":
                return "\b";
              case "f":
                return "\f";
              case "n":
                return "\n";
              case "r":
                return "\r";
              case "t":
                return "	";
              default:
                doFail(_state, "invalid escape sequence");
            }
          });
        } else if (chCode === 91) {
          _out.type = 2;
          pos++;
          char++;
        } else if (chCode === 123) {
          _out.type = 3;
          pos++;
          char++;
        } else if (chCode === 93) {
          _out.type = 4;
          pos++;
          char++;
        } else if (chCode === 125) {
          _out.type = 5;
          pos++;
          char++;
        } else if (chCode === 58) {
          _out.type = 6;
          pos++;
          char++;
        } else if (chCode === 44) {
          _out.type = 7;
          pos++;
          char++;
        } else if (chCode === 110) {
          _out.type = 8;
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 117) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 108) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 108) {
            return false;
          }
          pos++;
          char++;
        } else if (chCode === 116) {
          _out.type = 9;
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 114) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 117) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 101) {
            return false;
          }
          pos++;
          char++;
        } else if (chCode === 102) {
          _out.type = 10;
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 97) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 108) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 115) {
            return false;
          }
          pos++;
          char++;
          chCode = source.charCodeAt(pos);
          if (chCode !== 101) {
            return false;
          }
          pos++;
          char++;
        } else {
          _out.type = 11;
          do {
            if (pos >= len) {
              return false;
            }
            chCode = source.charCodeAt(pos);
            if (chCode === 46 || chCode >= 48 && chCode <= 57 || (chCode === 101 || chCode === 69) || (chCode === 45 || chCode === 43)) {
              pos++;
              char++;
              continue;
            }
            break;
          } while (true);
        }
        _out.len = pos - _out.offset;
        if (_out.value === null) {
          _out.value = source.substr(_out.offset, _out.len);
        }
        _state.pos = pos;
        _state.line = line;
        _state.char = char;
        return true;
      }
    }
  });

  // node_modules/monaco-textmate/dist/grammarReader.js
  var require_grammarReader = __commonJS({
    "node_modules/monaco-textmate/dist/grammarReader.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var plist = require_main();
      var debug_1 = require_debug();
      var json_1 = require_json();
      function parseJSONGrammar(contents, filename) {
        if (debug_1.CAPTURE_METADATA) {
          return json_1.parse(contents, filename, true);
        }
        return JSON.parse(contents);
      }
      exports.parseJSONGrammar = parseJSONGrammar;
      function parsePLISTGrammar(contents, filename) {
        if (debug_1.CAPTURE_METADATA) {
          return plist.parseWithLocation(contents, filename, "$vscodeTextmateLocation");
        }
        return plist.parse(contents);
      }
      exports.parsePLISTGrammar = parsePLISTGrammar;
    }
  });

  // node_modules/monaco-textmate/dist/theme.js
  var require_theme = __commonJS({
    "node_modules/monaco-textmate/dist/theme.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var ParsedThemeRule = (
        /** @class */
        /* @__PURE__ */ (function() {
          function ParsedThemeRule2(scope, parentScopes, index, fontStyle, foreground, background) {
            this.scope = scope;
            this.parentScopes = parentScopes;
            this.index = index;
            this.fontStyle = fontStyle;
            this.foreground = foreground;
            this.background = background;
          }
          return ParsedThemeRule2;
        })()
      );
      exports.ParsedThemeRule = ParsedThemeRule;
      function isValidHexColor(hex) {
        if (/^#[0-9a-f]{6}$/i.test(hex)) {
          return true;
        }
        if (/^#[0-9a-f]{8}$/i.test(hex)) {
          return true;
        }
        if (/^#[0-9a-f]{3}$/i.test(hex)) {
          return true;
        }
        if (/^#[0-9a-f]{4}$/i.test(hex)) {
          return true;
        }
        return false;
      }
      function parseTheme(source) {
        if (!source) {
          return [];
        }
        if (!source.settings || !Array.isArray(source.settings)) {
          return [];
        }
        var settings = source.settings;
        var result = [], resultLen = 0;
        for (var i = 0, len = settings.length; i < len; i++) {
          var entry = settings[i];
          if (!entry.settings) {
            continue;
          }
          var scopes = void 0;
          if (typeof entry.scope === "string") {
            var _scope = entry.scope;
            _scope = _scope.replace(/^[,]+/, "");
            _scope = _scope.replace(/[,]+$/, "");
            scopes = _scope.split(",");
          } else if (Array.isArray(entry.scope)) {
            scopes = entry.scope;
          } else {
            scopes = [""];
          }
          var fontStyle = -1;
          if (typeof entry.settings.fontStyle === "string") {
            fontStyle = 0;
            var segments = entry.settings.fontStyle.split(" ");
            for (var j = 0, lenJ = segments.length; j < lenJ; j++) {
              var segment = segments[j];
              switch (segment) {
                case "italic":
                  fontStyle = fontStyle | 1;
                  break;
                case "bold":
                  fontStyle = fontStyle | 2;
                  break;
                case "underline":
                  fontStyle = fontStyle | 4;
                  break;
              }
            }
          }
          var foreground = null;
          if (typeof entry.settings.foreground === "string" && isValidHexColor(entry.settings.foreground)) {
            foreground = entry.settings.foreground;
          }
          var background = null;
          if (typeof entry.settings.background === "string" && isValidHexColor(entry.settings.background)) {
            background = entry.settings.background;
          }
          for (var j = 0, lenJ = scopes.length; j < lenJ; j++) {
            var _scope = scopes[j].trim();
            var segments = _scope.split(" ");
            var scope = segments[segments.length - 1];
            var parentScopes = null;
            if (segments.length > 1) {
              parentScopes = segments.slice(0, segments.length - 1);
              parentScopes.reverse();
            }
            result[resultLen++] = new ParsedThemeRule(scope, parentScopes, i, fontStyle, foreground, background);
          }
        }
        return result;
      }
      exports.parseTheme = parseTheme;
      function resolveParsedThemeRules(parsedThemeRules) {
        parsedThemeRules.sort(function(a, b) {
          var r = strcmp(a.scope, b.scope);
          if (r !== 0) {
            return r;
          }
          r = strArrCmp(a.parentScopes, b.parentScopes);
          if (r !== 0) {
            return r;
          }
          return a.index - b.index;
        });
        var defaultFontStyle = 0;
        var defaultForeground = "#000000";
        var defaultBackground = "#ffffff";
        while (parsedThemeRules.length >= 1 && parsedThemeRules[0].scope === "") {
          var incomingDefaults = parsedThemeRules.shift();
          if (incomingDefaults.fontStyle !== -1) {
            defaultFontStyle = incomingDefaults.fontStyle;
          }
          if (incomingDefaults.foreground !== null) {
            defaultForeground = incomingDefaults.foreground;
          }
          if (incomingDefaults.background !== null) {
            defaultBackground = incomingDefaults.background;
          }
        }
        var colorMap = new ColorMap();
        var defaults = new ThemeTrieElementRule(0, null, defaultFontStyle, colorMap.getId(defaultForeground), colorMap.getId(defaultBackground));
        var root = new ThemeTrieElement(new ThemeTrieElementRule(0, null, -1, 0, 0), []);
        for (var i = 0, len = parsedThemeRules.length; i < len; i++) {
          var rule = parsedThemeRules[i];
          root.insert(0, rule.scope, rule.parentScopes, rule.fontStyle, colorMap.getId(rule.foreground), colorMap.getId(rule.background));
        }
        return new Theme(colorMap, defaults, root);
      }
      var ColorMap = (
        /** @class */
        (function() {
          function ColorMap2() {
            this._lastColorId = 0;
            this._id2color = [];
            this._color2id = /* @__PURE__ */ Object.create(null);
          }
          ColorMap2.prototype.getId = function(color) {
            if (color === null) {
              return 0;
            }
            color = color.toUpperCase();
            var value = this._color2id[color];
            if (value) {
              return value;
            }
            value = ++this._lastColorId;
            this._color2id[color] = value;
            this._id2color[value] = color;
            return value;
          };
          ColorMap2.prototype.getColorMap = function() {
            return this._id2color.slice(0);
          };
          return ColorMap2;
        })()
      );
      exports.ColorMap = ColorMap;
      var Theme = (
        /** @class */
        (function() {
          function Theme2(colorMap, defaults, root) {
            this._colorMap = colorMap;
            this._root = root;
            this._defaults = defaults;
            this._cache = {};
          }
          Theme2.createFromRawTheme = function(source) {
            return this.createFromParsedTheme(parseTheme(source));
          };
          Theme2.createFromParsedTheme = function(source) {
            return resolveParsedThemeRules(source);
          };
          Theme2.prototype.getColorMap = function() {
            return this._colorMap.getColorMap();
          };
          Theme2.prototype.getDefaults = function() {
            return this._defaults;
          };
          Theme2.prototype.match = function(scopeName) {
            if (!this._cache.hasOwnProperty(scopeName)) {
              this._cache[scopeName] = this._root.match(scopeName);
            }
            return this._cache[scopeName];
          };
          return Theme2;
        })()
      );
      exports.Theme = Theme;
      function strcmp(a, b) {
        if (a < b) {
          return -1;
        }
        if (a > b) {
          return 1;
        }
        return 0;
      }
      exports.strcmp = strcmp;
      function strArrCmp(a, b) {
        if (a === null && b === null) {
          return 0;
        }
        if (!a) {
          return -1;
        }
        if (!b) {
          return 1;
        }
        var len1 = a.length;
        var len2 = b.length;
        if (len1 === len2) {
          for (var i = 0; i < len1; i++) {
            var res = strcmp(a[i], b[i]);
            if (res !== 0) {
              return res;
            }
          }
          return 0;
        }
        return len1 - len2;
      }
      exports.strArrCmp = strArrCmp;
      var ThemeTrieElementRule = (
        /** @class */
        (function() {
          function ThemeTrieElementRule2(scopeDepth, parentScopes, fontStyle, foreground, background) {
            this.scopeDepth = scopeDepth;
            this.parentScopes = parentScopes;
            this.fontStyle = fontStyle;
            this.foreground = foreground;
            this.background = background;
          }
          ThemeTrieElementRule2.prototype.clone = function() {
            return new ThemeTrieElementRule2(this.scopeDepth, this.parentScopes, this.fontStyle, this.foreground, this.background);
          };
          ThemeTrieElementRule2.cloneArr = function(arr) {
            var r = [];
            for (var i = 0, len = arr.length; i < len; i++) {
              r[i] = arr[i].clone();
            }
            return r;
          };
          ThemeTrieElementRule2.prototype.acceptOverwrite = function(scopeDepth, fontStyle, foreground, background) {
            if (this.scopeDepth > scopeDepth) {
              console.log("how did this happen?");
            } else {
              this.scopeDepth = scopeDepth;
            }
            if (fontStyle !== -1) {
              this.fontStyle = fontStyle;
            }
            if (foreground !== 0) {
              this.foreground = foreground;
            }
            if (background !== 0) {
              this.background = background;
            }
          };
          return ThemeTrieElementRule2;
        })()
      );
      exports.ThemeTrieElementRule = ThemeTrieElementRule;
      var ThemeTrieElement = (
        /** @class */
        (function() {
          function ThemeTrieElement2(mainRule, rulesWithParentScopes, children) {
            if (rulesWithParentScopes === void 0) {
              rulesWithParentScopes = [];
            }
            if (children === void 0) {
              children = {};
            }
            this._mainRule = mainRule;
            this._rulesWithParentScopes = rulesWithParentScopes;
            this._children = children;
          }
          ThemeTrieElement2._sortBySpecificity = function(arr) {
            if (arr.length === 1) {
              return arr;
            }
            arr.sort(this._cmpBySpecificity);
            return arr;
          };
          ThemeTrieElement2._cmpBySpecificity = function(a, b) {
            if (a.scopeDepth === b.scopeDepth) {
              var aParentScopes = a.parentScopes;
              var bParentScopes = b.parentScopes;
              var aParentScopesLen = aParentScopes === null ? 0 : aParentScopes.length;
              var bParentScopesLen = bParentScopes === null ? 0 : bParentScopes.length;
              if (aParentScopesLen === bParentScopesLen) {
                for (var i = 0; i < aParentScopesLen; i++) {
                  var aLen = aParentScopes[i].length;
                  var bLen = bParentScopes[i].length;
                  if (aLen !== bLen) {
                    return bLen - aLen;
                  }
                }
              }
              return bParentScopesLen - aParentScopesLen;
            }
            return b.scopeDepth - a.scopeDepth;
          };
          ThemeTrieElement2.prototype.match = function(scope) {
            if (scope === "") {
              return ThemeTrieElement2._sortBySpecificity([].concat(this._mainRule).concat(this._rulesWithParentScopes));
            }
            var dotIndex = scope.indexOf(".");
            var head;
            var tail;
            if (dotIndex === -1) {
              head = scope;
              tail = "";
            } else {
              head = scope.substring(0, dotIndex);
              tail = scope.substring(dotIndex + 1);
            }
            if (this._children.hasOwnProperty(head)) {
              return this._children[head].match(tail);
            }
            return ThemeTrieElement2._sortBySpecificity([].concat(this._mainRule).concat(this._rulesWithParentScopes));
          };
          ThemeTrieElement2.prototype.insert = function(scopeDepth, scope, parentScopes, fontStyle, foreground, background) {
            if (scope === "") {
              this._doInsertHere(scopeDepth, parentScopes, fontStyle, foreground, background);
              return;
            }
            var dotIndex = scope.indexOf(".");
            var head;
            var tail;
            if (dotIndex === -1) {
              head = scope;
              tail = "";
            } else {
              head = scope.substring(0, dotIndex);
              tail = scope.substring(dotIndex + 1);
            }
            var child;
            if (this._children.hasOwnProperty(head)) {
              child = this._children[head];
            } else {
              child = new ThemeTrieElement2(this._mainRule.clone(), ThemeTrieElementRule.cloneArr(this._rulesWithParentScopes));
              this._children[head] = child;
            }
            child.insert(scopeDepth + 1, tail, parentScopes, fontStyle, foreground, background);
          };
          ThemeTrieElement2.prototype._doInsertHere = function(scopeDepth, parentScopes, fontStyle, foreground, background) {
            if (parentScopes === null) {
              this._mainRule.acceptOverwrite(scopeDepth, fontStyle, foreground, background);
              return;
            }
            for (var i = 0, len = this._rulesWithParentScopes.length; i < len; i++) {
              var rule = this._rulesWithParentScopes[i];
              if (strArrCmp(rule.parentScopes, parentScopes) === 0) {
                rule.acceptOverwrite(scopeDepth, fontStyle, foreground, background);
                return;
              }
            }
            if (fontStyle === -1) {
              fontStyle = this._mainRule.fontStyle;
            }
            if (foreground === 0) {
              foreground = this._mainRule.foreground;
            }
            if (background === 0) {
              background = this._mainRule.background;
            }
            this._rulesWithParentScopes.push(new ThemeTrieElementRule(scopeDepth, parentScopes, fontStyle, foreground, background));
          };
          return ThemeTrieElement2;
        })()
      );
      exports.ThemeTrieElement = ThemeTrieElement;
    }
  });

  // node_modules/monaco-textmate/dist/main.js
  var require_main2 = __commonJS({
    "node_modules/monaco-textmate/dist/main.js"(exports) {
      "use strict";
      var __awaiter = exports && exports.__awaiter || function(thisArg, _arguments, P, generator) {
        return new (P || (P = Promise))(function(resolve, reject) {
          function fulfilled(value) {
            try {
              step(generator.next(value));
            } catch (e) {
              reject(e);
            }
          }
          function rejected(value) {
            try {
              step(generator["throw"](value));
            } catch (e) {
              reject(e);
            }
          }
          function step(result) {
            result.done ? resolve(result.value) : new P(function(resolve2) {
              resolve2(result.value);
            }).then(fulfilled, rejected);
          }
          step((generator = generator.apply(thisArg, _arguments || [])).next());
        });
      };
      var __generator = exports && exports.__generator || function(thisArg, body) {
        var _ = { label: 0, sent: function() {
          if (t[0] & 1) throw t[1];
          return t[1];
        }, trys: [], ops: [] }, f, y, t, g;
        return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() {
          return this;
        }), g;
        function verb(n) {
          return function(v) {
            return step([n, v]);
          };
        }
        function step(op) {
          if (f) throw new TypeError("Generator is already executing.");
          while (_) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
              case 0:
              case 1:
                t = op;
                break;
              case 4:
                _.label++;
                return { value: op[1], done: false };
              case 5:
                _.label++;
                y = op[1];
                op = [0];
                continue;
              case 7:
                op = _.ops.pop();
                _.trys.pop();
                continue;
              default:
                if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) {
                  _ = 0;
                  continue;
                }
                if (op[0] === 3 && (!t || op[1] > t[0] && op[1] < t[3])) {
                  _.label = op[1];
                  break;
                }
                if (op[0] === 6 && _.label < t[1]) {
                  _.label = t[1];
                  t = op;
                  break;
                }
                if (t && _.label < t[2]) {
                  _.label = t[2];
                  _.ops.push(op);
                  break;
                }
                if (t[2]) _.ops.pop();
                _.trys.pop();
                continue;
            }
            op = body.call(thisArg, _);
          } catch (e) {
            op = [6, e];
            y = 0;
          } finally {
            f = t = 0;
          }
          if (op[0] & 5) throw op[1];
          return { value: op[0] ? op[1] : void 0, done: true };
        }
      };
      Object.defineProperty(exports, "__esModule", { value: true });
      var registry_1 = require_registry();
      var grammarReader_1 = require_grammarReader();
      var theme_1 = require_theme();
      var grammar_1 = require_grammar();
      var DEFAULT_OPTIONS = {
        getGrammarDefinition: function(scopeName) {
          return null;
        },
        getInjections: function(scopeName) {
          return null;
        }
      };
      var Registry = (
        /** @class */
        (function() {
          function Registry2(locator) {
            if (locator === void 0) {
              locator = DEFAULT_OPTIONS;
            }
            this._locator = locator;
            this._syncRegistry = new registry_1.SyncRegistry(theme_1.Theme.createFromRawTheme(locator.theme));
            this.installationQueue = /* @__PURE__ */ new Map();
          }
          Registry2.prototype.setTheme = function(theme) {
            this._syncRegistry.setTheme(theme_1.Theme.createFromRawTheme(theme));
          };
          Registry2.prototype.getColorMap = function() {
            return this._syncRegistry.getColorMap();
          };
          Registry2.prototype.loadGrammarWithEmbeddedLanguages = function(initialScopeName, initialLanguage, embeddedLanguages) {
            return this.loadGrammarWithConfiguration(initialScopeName, initialLanguage, { embeddedLanguages });
          };
          Registry2.prototype.loadGrammarWithConfiguration = function(initialScopeName, initialLanguage, configuration) {
            return __awaiter(this, void 0, void 0, function() {
              return __generator(this, function(_a) {
                switch (_a.label) {
                  case 0:
                    return [4, this._loadGrammar(initialScopeName)];
                  case 1:
                    _a.sent();
                    return [2, this.grammarForScopeName(initialScopeName, initialLanguage, configuration.embeddedLanguages, configuration.tokenTypes)];
                }
              });
            });
          };
          Registry2.prototype.loadGrammar = function(initialScopeName) {
            return __awaiter(this, void 0, void 0, function() {
              return __generator(this, function(_a) {
                return [2, this._loadGrammar(initialScopeName)];
              });
            });
          };
          Registry2.prototype._loadGrammar = function(initialScopeName, dependentScope) {
            if (dependentScope === void 0) {
              dependentScope = null;
            }
            return __awaiter(this, void 0, void 0, function() {
              var prom;
              var _this = this;
              return __generator(this, function(_a) {
                switch (_a.label) {
                  case 0:
                    if (this._syncRegistry.lookup(initialScopeName)) {
                      return [2, this.grammarForScopeName(initialScopeName)];
                    }
                    if (this.installationQueue.has(initialScopeName)) {
                      return [2, this.installationQueue.get(initialScopeName)];
                    }
                    prom = new Promise(function(resolve, reject) {
                      return __awaiter(_this, void 0, void 0, function() {
                        var grammarDefinition, rawGrammar, injections, deps;
                        var _this2 = this;
                        return __generator(this, function(_a2) {
                          switch (_a2.label) {
                            case 0:
                              return [4, this._locator.getGrammarDefinition(initialScopeName, dependentScope)];
                            case 1:
                              grammarDefinition = _a2.sent();
                              if (!grammarDefinition) {
                                throw new Error("A tmGrammar load was requested but registry host failed to provide grammar definition");
                              }
                              if (grammarDefinition.format !== "json" && grammarDefinition.format !== "plist" || grammarDefinition.format === "json" && typeof grammarDefinition.content !== "object" && typeof grammarDefinition.content !== "string" || grammarDefinition.format === "plist" && typeof grammarDefinition.content !== "string") {
                                throw new TypeError('Grammar definition must be an object, either `{ content: string | object, format: "json" }` OR `{ content: string, format: "plist" }`)');
                              }
                              rawGrammar = grammarDefinition.format === "json" ? typeof grammarDefinition.content === "string" ? grammarReader_1.parseJSONGrammar(grammarDefinition.content, "c://fakepath/grammar.json") : grammarDefinition.content : grammarReader_1.parsePLISTGrammar(grammarDefinition.content, "c://fakepath/grammar.plist");
                              injections = typeof this._locator.getInjections === "function" && this._locator.getInjections(initialScopeName);
                              rawGrammar.scopeName = initialScopeName;
                              deps = this._syncRegistry.addGrammar(rawGrammar, injections);
                              return [4, Promise.all(deps.map(function(scopeNameD) {
                                return __awaiter(_this2, void 0, void 0, function() {
                                  return __generator(this, function(_a3) {
                                    try {
                                      return [2, this._loadGrammar(scopeNameD, initialScopeName)];
                                    } catch (error) {
                                      throw new Error("While trying to load tmGrammar with scopeId: '" + initialScopeName + "', it's dependency (scopeId: " + scopeNameD + ") loading errored: " + error.message);
                                    }
                                    return [
                                      2
                                      /*return*/
                                    ];
                                  });
                                });
                              }))];
                            case 2:
                              _a2.sent();
                              resolve(this.grammarForScopeName(initialScopeName));
                              return [
                                2
                                /*return*/
                              ];
                          }
                        });
                      });
                    });
                    this.installationQueue.set(initialScopeName, prom);
                    return [4, prom];
                  case 1:
                    _a.sent();
                    this.installationQueue.delete(initialScopeName);
                    return [2, prom];
                }
              });
            });
          };
          Registry2.prototype.grammarForScopeName = function(scopeName, initialLanguage, embeddedLanguages, tokenTypes) {
            if (initialLanguage === void 0) {
              initialLanguage = 0;
            }
            if (embeddedLanguages === void 0) {
              embeddedLanguages = null;
            }
            if (tokenTypes === void 0) {
              tokenTypes = null;
            }
            return this._syncRegistry.grammarForScopeName(scopeName, initialLanguage, embeddedLanguages, tokenTypes);
          };
          return Registry2;
        })()
      );
      exports.Registry = Registry;
      exports.INITIAL = grammar_1.StackElement.NULL;
    }
  });

  // node_modules/monaco-editor-textmate/dist/tm-to-monaco-token.js
  var require_tm_to_monaco_token = __commonJS({
    "node_modules/monaco-editor-textmate/dist/tm-to-monaco-token.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.TMToMonacoToken = void 0;
      var TMToMonacoToken = (editor, scopes) => {
        let scopeName = "";
        for (let i = scopes[0].length - 1; i >= 0; i -= 1) {
          const char = scopes[0][i];
          if (char === ".") {
            break;
          }
          scopeName = char + scopeName;
        }
        for (let i = scopes.length - 1; i >= 0; i -= 1) {
          const scope = scopes[i];
          for (let i2 = scope.length - 1; i2 >= 0; i2 -= 1) {
            const char = scope[i2];
            if (char === ".") {
              const token = scope.slice(0, i2);
              if (editor["_themeService"]._theme._tokenTheme._match(token + "." + scopeName)._foreground > 1) {
                return token + "." + scopeName;
              }
              if (editor["_themeService"]._theme._tokenTheme._match(token)._foreground > 1) {
                return token;
              }
            }
          }
        }
        return "";
      };
      exports.TMToMonacoToken = TMToMonacoToken;
    }
  });

  // node_modules/monaco-editor-textmate/dist/index.js
  var require_dist = __commonJS({
    "node_modules/monaco-editor-textmate/dist/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.wireTmGrammars = void 0;
      var monaco_textmate_1 = require_main2();
      var tm_to_monaco_token_1 = require_tm_to_monaco_token();
      var TokenizerState = class _TokenizerState {
        _ruleStack;
        constructor(_ruleStack) {
          this._ruleStack = _ruleStack;
        }
        get ruleStack() {
          return this._ruleStack;
        }
        clone() {
          return new _TokenizerState(this._ruleStack);
        }
        equals(other) {
          if (!other || !(other instanceof _TokenizerState) || other !== this || other._ruleStack !== this._ruleStack) {
            return false;
          }
          return true;
        }
      };
      function wireTmGrammars(monaco, registry, languages, editor) {
        return Promise.all(Array.from(languages.keys()).map(async (languageId) => {
          const grammar = await registry.loadGrammar(languages.get(languageId));
          monaco.languages.setTokensProvider(languageId, {
            getInitialState: () => new TokenizerState(monaco_textmate_1.INITIAL),
            tokenize: (line, state) => {
              const res = grammar.tokenizeLine(line, state.ruleStack);
              return {
                endState: new TokenizerState(res.ruleStack),
                tokens: res.tokens.map((token) => ({
                  ...token,
                  // TODO: At the moment, monaco-editor doesn't seem to accept array of scopes
                  scopes: editor ? (0, tm_to_monaco_token_1.TMToMonacoToken)(editor, token.scopes) : token.scopes[token.scopes.length - 1]
                }))
              };
            }
          });
        }));
      }
      exports.wireTmGrammars = wireTmGrammars;
    }
  });

  // entry.js
  var require_entry = __commonJS({
    "entry.js"() {
      var import_onigasm = __toESM(require_lib());
      var import_monaco_textmate = __toESM(require_main2());
      var import_monaco_editor_textmate = __toESM(require_dist());
      var wasmReady = null;
      function ensureWasm(url) {
        if (!wasmReady) {
          wasmReady = (0, import_onigasm.loadWASM)(url).catch(function(e) {
            wasmReady = null;
            throw e;
          });
        }
        return wasmReady;
      }
      async function wire(monaco, grammars) {
        await ensureWasm("/vendor/textmate/onigasm.wasm");
        var scopeToGrammar = {};
        var languages = /* @__PURE__ */ new Map();
        (grammars || []).forEach(function(g) {
          if (!g || !g.scopeName || !g.language || !g.grammar) {
            return;
          }
          scopeToGrammar[g.scopeName] = g.grammar;
          languages.set(g.language, g.scopeName);
          var exists = monaco.languages.getLanguages().some(function(l) {
            return l.id === g.language;
          });
          if (!exists) {
            monaco.languages.register({ id: g.language });
          }
        });
        if (languages.size === 0) {
          return;
        }
        var registry = new import_monaco_textmate.Registry({
          getGrammarDefinition: async function(scopeName) {
            var src = scopeToGrammar[scopeName];
            return { format: "json", content: src && typeof src !== "string" ? JSON.stringify(src) : src || "{}" };
          }
        });
        await (0, import_monaco_editor_textmate.wireTmGrammars)(monaco, registry, languages);
      }
      window.GeramTextmate = { wire };
    }
  });
  require_entry();
})();
