// Deriv WebSocket API Client
const DERIV_APP_ID = process.env.NEXT_PUBLIC_DERIV_APP_ID || "1089"
const WS_URL = `wss://ws.derivws.com/websockets/v3?app_id=${DERIV_APP_ID}`

export interface TickData {
  symbol: string
  quote: number
  epoch: number
  pip_size: number
}

export interface ContractProposal {
  id: string
  ask_price: number
  payout: number
  spot: number
  date_expiry: number
}

export interface TradeResult {
  contract_id: number
  buy_price: number
  payout: number
  profit: number
  status: "won" | "lost" | "open"
}

export class DerivAPI {
  private ws: WebSocket | null = null
  private token: string
  private reqId = 0
  private callbacks: Map<number, (data: any) => void> = new Map()
  private tickSubscribers: Map<string, (tick: TickData) => void> = new Map()
  private isConnected = false
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5

  constructor(token: string) {
    this.token = token
  }

  async connect(): Promise<boolean> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(WS_URL)

        this.ws.onopen = () => {
          this.isConnected = true
          this.reconnectAttempts = 0
          // Authorize
          this.send({ authorize: this.token }).then((res) => {
            if (res.authorize) {
              resolve(true)
            } else {
              reject(res.error)
            }
          })
        }

        this.ws.onmessage = (event) => {
          const data = JSON.parse(event.data)

          // Handle tick updates
          if (data.tick) {
            const tick: TickData = {
              symbol: data.tick.symbol,
              quote: data.tick.quote,
              epoch: data.tick.epoch,
              pip_size: data.tick.pip_size,
            }
            const subscriber = this.tickSubscribers.get(data.tick.symbol)
            if (subscriber) {
              subscriber(tick)
            }
          }

          // Handle request responses
          if (data.req_id && this.callbacks.has(data.req_id)) {
            const callback = this.callbacks.get(data.req_id)
            callback?.(data)
            this.callbacks.delete(data.req_id)
          }
        }

        this.ws.onerror = (error) => {
          console.error("WebSocket error:", error)
          reject(error)
        }

        this.ws.onclose = () => {
          this.isConnected = false
          this.attemptReconnect()
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      setTimeout(() => {
        this.connect()
      }, 2000 * this.reconnectAttempts)
    }
  }

  private send(request: any): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!this.ws || !this.isConnected) {
        reject(new Error("Not connected"))
        return
      }

      const reqId = ++this.reqId
      this.callbacks.set(reqId, resolve)
      this.ws.send(JSON.stringify({ ...request, req_id: reqId }))

      // Timeout after 30s
      setTimeout(() => {
        if (this.callbacks.has(reqId)) {
          this.callbacks.delete(reqId)
          reject(new Error("Request timeout"))
        }
      }, 30000)
    })
  }

  async getBalance(): Promise<{ balance: number; currency: string }> {
    const res = await this.send({ balance: 1 })
    return {
      balance: res.balance.balance,
      currency: res.balance.currency,
    }
  }

  async subscribeTicks(symbol: string, callback: (tick: TickData) => void): Promise<void> {
    this.tickSubscribers.set(symbol, callback)
    await this.send({ ticks: symbol, subscribe: 1 })
  }

  async unsubscribeTicks(symbol: string): Promise<void> {
    this.tickSubscribers.delete(symbol)
    await this.send({ forget_all: "ticks" })
  }

  async getTickHistory(symbol: string, count = 100): Promise<TickData[]> {
    const res = await this.send({
      ticks_history: symbol,
      count: count,
      end: "latest",
      style: "ticks",
    })

    if (res.history) {
      return res.history.prices.map((price: number, i: number) => ({
        symbol,
        quote: price,
        epoch: res.history.times[i],
        pip_size: 2,
      }))
    }
    return []
  }

  async getProposal(params: {
    contract_type: string
    symbol: string
    duration: number
    duration_unit: string
    amount: number
    basis: string
    barrier?: string | number
  }): Promise<ContractProposal> {
    const res = await this.send({
      proposal: 1,
      ...params,
    })

    return {
      id: res.proposal.id,
      ask_price: res.proposal.ask_price,
      payout: res.proposal.payout,
      spot: res.proposal.spot,
      date_expiry: res.proposal.date_expiry,
    }
  }

  async buyContract(proposalId: string, price: number): Promise<TradeResult> {
    const res = await this.send({
      buy: proposalId,
      price: price,
    })

    return {
      contract_id: res.buy.contract_id,
      buy_price: res.buy.buy_price,
      payout: res.buy.payout,
      profit: 0,
      status: "open",
    }
  }

  async getContractUpdate(contractId: number): Promise<TradeResult> {
    const res = await this.send({
      proposal_open_contract: 1,
      contract_id: contractId,
    })

    const contract = res.proposal_open_contract
    return {
      contract_id: contract.contract_id,
      buy_price: contract.buy_price,
      payout: contract.payout,
      profit: contract.profit,
      status: contract.status === "won" ? "won" : contract.status === "lost" ? "lost" : "open",
    }
  }

  async getActiveSymbols(): Promise<Array<{ symbol: string; display_name: string; market: string }>> {
    const res = await this.send({ active_symbols: "brief", product_type: "basic" })
    return res.active_symbols.map((s: any) => ({
      symbol: s.symbol,
      display_name: s.display_name,
      market: s.market,
    }))
  }

  disconnect() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.isConnected = false
    this.callbacks.clear()
    this.tickSubscribers.clear()
  }
}

// Singleton instance manager
let apiInstance: DerivAPI | null = null

export function getDerivAPI(): DerivAPI | null {
  if (typeof window === "undefined") return null

  if (!apiInstance) {
    const token = localStorage.getItem("deriv_token")
    if (token) {
      apiInstance = new DerivAPI(token)
    }
  }
  return apiInstance
}

export function createDerivAPI(token: string): DerivAPI {
  if (apiInstance) {
    apiInstance.disconnect()
  }
  apiInstance = new DerivAPI(token)
  return apiInstance
}

export function disconnectDerivAPI() {
  if (apiInstance) {
    apiInstance.disconnect()
    apiInstance = null
  }
}
