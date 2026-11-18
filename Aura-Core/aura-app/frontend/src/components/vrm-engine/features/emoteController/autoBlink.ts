import { VRMExpressionManager } from "@pixiv/three-vrm";
import { BLINK_CLOSE_MAX, BLINK_OPEN_MAX } from "./emoteConstants";

/**
 * è‡ªå‹•çž¬ãã‚’åˆ¶å¾¡ã™ã‚‹ã‚¯ãƒ©ã‚¹
 */
export class AutoBlink {
  private _expressionManager: VRMExpressionManager;
  private _remainingTime: number;
  private _isOpen: boolean;
  private _isAutoBlink: boolean;

  constructor(expressionManager: VRMExpressionManager) {
    this._expressionManager = expressionManager;
    this._remainingTime = 0;
    this._isAutoBlink = true;
    this._isOpen = true;
  }

  /**
   * è‡ªå‹•çž¬ãã‚’ON/OFFã™ã‚‹ã€‚
   *
   * ç›®ã‚’é–‰ã˜ã¦ã„ã‚‹(blinkãŒ1ã®)æ™‚ã«æ„Ÿæƒ…è¡¨ç¾ã‚’å…¥ã‚Œã¦ã—ã¾ã†ã¨ä¸è‡ªç„¶ã«ãªã‚‹ã®ã§ã€
   * ç›®ãŒé–‹ãã¾ã§ã®ç§’ã‚’è¿”ã—ã€ãã®æ™‚é–“å¾…ã£ã¦ã‹ã‚‰æ„Ÿæƒ…è¡¨ç¾ã‚’é©ç”¨ã™ã‚‹ã€‚
   * @param isAuto
   * @returns ç›®ãŒé–‹ãã¾ã§ã®ç§’
   */
  public setEnable(isAuto: boolean) {
    this._isAutoBlink = isAuto;

    // ç›®ãŒé–‰ã˜ã¦ã„ã‚‹å ´åˆã€ç›®ãŒé–‹ãã¾ã§ã®æ™‚é–“ã‚’è¿”ã™
    if (!this._isOpen) {
      return this._remainingTime;
    }

    return 0;
  }

  public update(delta: number) {
    if (this._remainingTime > 0) {
      this._remainingTime -= delta;
      return;
    }

    if (this._isOpen && this._isAutoBlink) {
      this.close();
      return;
    }

    this.open();
  }

  private close() {
    this._isOpen = false;
    this._remainingTime = BLINK_CLOSE_MAX;
    this._expressionManager.setValue("blink", 1);
  }

  private open() {
    this._isOpen = true;
    this._remainingTime = BLINK_OPEN_MAX;
    this._expressionManager.setValue("blink", 0);
  }
}




