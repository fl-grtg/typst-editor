/* esm.sh - lib0@0.2.119/error */
var t=e=>new Error(e),o=()=>{throw t("Method unimplemented")},r=()=>{throw t("Unexpected case")},n=e=>{if(!e)throw t("Assert failed")};export{n as assert,t as create,o as methodUnimplemented,r as unexpectedCase};
