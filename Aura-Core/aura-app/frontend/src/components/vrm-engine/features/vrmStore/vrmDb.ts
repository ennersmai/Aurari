import { VrmDexieMock, type Table } from "../../mockDependencies";
import VrmDbModel from "./vrmDbModel";

export class VrmDexie extends VrmDexieMock<VrmDbModel> {
  // vrms is inherited from VrmDexieMock — do NOT redeclare it here.
  // Redeclaring would overwrite the parent's constructor-initialized value
  // with undefined due to ES class field semantics.

  constructor() {
    super();
  }
}

export const db = new VrmDexie();
