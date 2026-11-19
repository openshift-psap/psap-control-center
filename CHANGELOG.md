# Changelog

## [1.7.0](https://github.com/openshift-psap/psap-control-center/compare/psap-control-center-v1.6.0...psap-control-center-v1.7.0) (2026-11-19)


### Features

* add editable History filter comboboxes ([07d3335](https://github.com/openshift-psap/psap-control-center/commit/07d33351470987b454d05dc2627c97901040b364))
* add editable History filter comboboxes ([f152899](https://github.com/openshift-psap/psap-control-center/commit/f152899bf83ea10ffde8877514e5c165d43b132a))
* add generic run grouping ([c282266](https://github.com/openshift-psap/psap-control-center/commit/c28226612c7687fddfef467af57e2d53466a8e91))
* add generic run grouping ([11cdede](https://github.com/openshift-psap/psap-control-center/commit/11cdede34638827c2ca7a966c514250f48506b66))
* add RHAIIS dashboard parity ([4d996c3](https://github.com/openshift-psap/psap-control-center/commit/4d996c33a31580b676285edb8ca9cd0658ba3b5e))
* add searchable saved run history views ([c3b853e](https://github.com/openshift-psap/psap-control-center/commit/c3b853e64bd651185d649809562d30746979b19b))
* add searchable saved run history views ([19be121](https://github.com/openshift-psap/psap-control-center/commit/19be1216dacfa43581151f615d2bbec2b7e5c08a))
* add test run work item associations ([fcb5f84](https://github.com/openshift-psap/psap-control-center/commit/fcb5f848e22ff9889859c69d8393dc3e0a9e7b0d))
* add test run work item associations ([49ba667](https://github.com/openshift-psap/psap-control-center/commit/49ba6673e4c22d20a5089cdccf602e8510aa22c5))
* filter testing runs by authenticated requester ([cd32506](https://github.com/openshift-psap/psap-control-center/commit/cd32506babc3c2f05cb48e7c75e242b92961f186)), closes [#50](https://github.com/openshift-psap/psap-control-center/issues/50)
* persist exact PR request provenance ([464fed4](https://github.com/openshift-psap/psap-control-center/commit/464fed49cbbf6fe49b532c1957915aaf40e8c605))
* persist PR request provenance ([657235b](https://github.com/openshift-psap/psap-control-center/commit/657235bb59ca49d345ddda5a67485ed55df2d279))
* preserve and classify step-level test failures ([3c52f7b](https://github.com/openshift-psap/psap-control-center/commit/3c52f7b80c275b1cf09053f9432913b66110e8e6))
* preserve step-level failure details ([e44c02e](https://github.com/openshift-psap/psap-control-center/commit/e44c02e1e9840ea2a343b5c49dac9a2449df4143))
* promote development features and cluster refresh improvements to production ([a7a0583](https://github.com/openshift-psap/psap-control-center/commit/a7a0583165344bf0616dd3d2a7aa9a4951e34ee1))
* remember cluster refresh display mode ([#101](https://github.com/openshift-psap/psap-control-center/issues/101)) ([6f36af8](https://github.com/openshift-psap/psap-control-center/commit/6f36af8e2e0ef4136636b8a505c57e2e2d90745d)), closes [#31](https://github.com/openshift-psap/psap-control-center/issues/31)
* **testing:** record actual Forge execution provenance ([f1b7267](https://github.com/openshift-psap/psap-control-center/commit/f1b726796f58b9264b02d2daf754bff425acb3b1))
* **testing:** record Forge execution provenance ([3f9fdf8](https://github.com/openshift-psap/psap-control-center/commit/3f9fdf87aa1819b63ec0d7c935dbdbf087c9240c))


### Bug Fixes

* align RHAIIS form behavior and guidance ([b31640b](https://github.com/openshift-psap/psap-control-center/commit/b31640b7a5b6bfb33c56d41e4981a168aaa0f87e))
* **auth:** preload sign-in configuration ([488e258](https://github.com/openshift-psap/psap-control-center/commit/488e258356df32af04fa7303d8a17742b759d948))
* **auth:** preload sign-in configuration ([baa23ea](https://github.com/openshift-psap/psap-control-center/commit/baa23eac1cb659fdb3edc713d7fed077a2f867a6))
* count legacy GPU requests on DRA nodes ([69d88ba](https://github.com/openshift-psap/psap-control-center/commit/69d88ba47fa378e1fbb994cfcab92c8e1c6795d9))
* harden RHAIIS submission paths ([fe78bb8](https://github.com/openshift-psap/psap-control-center/commit/fe78bb82bdfb97d553ea925c6417f5a11843b469))
* keep cluster discovery and sign-in responsive ([06193e7](https://github.com/openshift-psap/psap-control-center/commit/06193e723d94816386339ffea8c970fbcfe134f5))
* speed up cluster status refresh ([0625bd4](https://github.com/openshift-psap/psap-control-center/commit/0625bd4dca2c0c2c948dcaabb4773036135ebaad))
* **testing:** load successful archived job details ([1d8f185](https://github.com/openshift-psap/psap-control-center/commit/1d8f1859cb86b6c01b67db31da4ef304a953619c))
* **testing:** load successful archived job details ([c21d509](https://github.com/openshift-psap/psap-control-center/commit/c21d5097df3969870ed88b95d5e4ed589cd38ad4))
* **testing:** preserve actionable pipeline failure details ([#80](https://github.com/openshift-psap/psap-control-center/issues/80)) ([63701b0](https://github.com/openshift-psap/psap-control-center/commit/63701b0d01be23795f77faf159da22d6bec06532))


### Performance Improvements

* refresh cluster data every three minutes ([06be462](https://github.com/openshift-psap/psap-control-center/commit/06be462293e168661ff2bd10ec92dc5e75aa9ffb))

## [1.6.0](https://github.com/openshift-psap/psap-control-center/compare/psap-control-center-v1.5.0...psap-control-center-v1.6.0) (2026-09-25)


### Features

* derive testing requester from authenticated user ([#71](https://github.com/openshift-psap/psap-control-center/issues/71)) ([#73](https://github.com/openshift-psap/psap-control-center/issues/73)) ([4e294f4](https://github.com/openshift-psap/psap-control-center/commit/4e294f450a277d9c448abfa78a847107578d19f3))


### Bug Fixes

* pin image updater CLI digest ([#70](https://github.com/openshift-psap/psap-control-center/issues/70)) ([94487ba](https://github.com/openshift-psap/psap-control-center/commit/94487ba4360bc5754c2c1c3c0176b7ac4336a823))

## 1.5.0 (2026-09-25)


### Features

* automate semantic releases ([#68](https://github.com/openshift-psap/psap-control-center/issues/68)) ([dec4df0](https://github.com/openshift-psap/psap-control-center/commit/dec4df030073210054a9fc12754c00c39f404d94))
