import numpy as np
import talib
import pandas
import scipy as sp
import scipy.optimize
import datetime as dt
from scipy import linalg as sla
from scipy import spatial
from jqdata import gta


#初始化方法，在整个回测、模拟实盘中最开始执行一次
#用于初始一些全局变量
def initialize(context):
    #用沪深 300 做回报基准
    set_benchmark('000300.XSHG')

    set_slippage(FixedSlippage(0.002))
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    # 过滤掉order系列API产生的比error级别低的log
    #log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

    context.lowPEG_position_price = {}
    context.QuantLib = QuantLib()

    #run_daily(fun_main, '10:30')



## 开盘前运行函数， 缺省系统回调函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    context.lowPEG_ratio = 1.0
    init_stock_list(context)
    lowPEG_trade_ratio = cal_PEG(context, context.lowPEG_ratio, context.portfolio.portfolio_value)
    #log.debug("计算完PEG的df\n %s" % (context.stock_df[:2]))


## 开盘时运行函数， 缺省系统回调函数
def market_open(context):
    log.info('market_open 执行')

## 收盘后运行函数, 缺省系统回调函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')

##准备股票列表
def init_stock_list(context):

    today = context.current_dt
    # 股票池,初始化函数时是空
    # 返回dataframe 格式：
    #                   display_name	name	  start_date
    #  000001.XSHE	    平安银行	    PAYH	   1991-04-03
    #  000002.XSHE	    万 科Ａ	    WKA	        1991-01-29
    context.stock_df = get_all_securities(['stock'], today)
    del context.stock_df['end_date']
    del context.stock_df['type']

    #为了后面方便拼凑两个dataframe，添加一个code列
    context.stock_df.insert(0, 'code', context.stock_df.index.tolist())

    stock_list = list(context.stock_df.index)

    q = query(valuation
                ).filter(valuation.code.in_(stock_list))
    #查询股票的财务数据，返回dataframe，结果中的缺失的数据使用0 填充
    df = get_fundamentals(q).fillna(value=0)


    #将股票的财务数据，股票名称拼成一个df
    context.stock_df = pd.merge(context.stock_df, df, on=['code','code'])
    context.stock_df.set_index('code')

    #log.debug("添加股票财务数据的df\n %s" % (context.stock_df[:2]))


def cal_PEG(context, lowPEG_ratio, portfolio_value):
    '''
    计算所有股票的PEG
    输入参数：lowPEG_ratio, protfolio_value
    输出参数：lowPEG_trade_ratio
    自有类  : PEG_lib
    调用类  : QuantLib
    '''
    # for lowPEG algorithms
    # 正态分布概率表，标准差倍数以及置信率
    # 1.96, 95%; 2.06, 96%; 2.18, 97%; 2.34, 98%; 2.58, 99%; 5, 99.9999%
    context.lowPEG_confidencelevel = 1.96
    context.lowPEG_hold_periods = 0
    # 引用 lib，lowPEG类
    g.PEGLib = PEG_lib()
    # 引用 QuantLib
    g.QuantLib = QuantLib()

    #log.debug("获得不适用LowPEG算法的股票代码")
    g.PEGLib.get_unuse_PEG_stock_list()
    #log.debug("计算其他股票的PEG")
    g.PEGLib.fun_cal_stock_PEG(context)
    #log.debug("PEG：stock_list:\n %s" % (context.stock_df[:5]))

class PEG_lib():
    #不适用lowPEG算法的股票代码列表
    unuse_PEG_stock_list = []
    def __init__(self, _period = '1d'):
        pass

    def fun_get_inc(self, context, stock_list):
        '''
            取得净利润增长率参数
            返回一个字典的字典： sock_dict，每个股票一个字典
                sick_dict[stock_code]['avg_inc']：过去4个季度平均增长率
                sick_dict[stock_code]['last_inc']：最后一个季度的增占率
                sick_dict[stock_code]['inc_std']：增长标准差
        '''

        # 取最近的四个季度财报的日期
        def __get_quarter(stock_list):
            '''
            输入 stock_list
            返回最近 n 个财报的日期
            返回每个股票最近一个财报的日期
            '''
            # 取最新一季度的统计日期
            q = query(indicator.code, indicator.statDate
                     ).filter(indicator.code.in_(stock_list))
            df = get_fundamentals(q)

            if len(stock_list) <= 0:
                log.error("stock list 长度为0")


            stock_last_statDate = {}
            tmpDict = df.to_dict()

            #log.info("stock_last_statDate之后的df %s" % (df))
            for i in range(len(tmpDict['statDate'].keys())):
                # 取得每个股票的代码，以及最新的财报发布日
                stock_last_statDate[tmpDict['code'][i]] = tmpDict['statDate'][i]

            df = df.sort(columns='statDate', ascending=False)
            # 取得最新的财报日期
            last_statDate = df.iloc[0,1]

            this_year = int(str(last_statDate)[0:4])
            this_month = str(last_statDate)[5:7]

            if this_month == '12':
                last_quarter       = str(this_year)     + 'q4'
                last_two_quarter   = str(this_year)     + 'q3'
                last_three_quarter = str(this_year)     + 'q2'
                last_four_quarter  = str(this_year)     + 'q1'
                last_five_quarter  = str(this_year - 1) + 'q4'

            elif this_month == '09':
                last_quarter       = str(this_year)     + 'q3'
                last_two_quarter   = str(this_year)     + 'q2'
                last_three_quarter = str(this_year)     + 'q1'
                last_four_quarter  = str(this_year - 1) + 'q4'
                last_five_quarter  = str(this_year - 1) + 'q3'

            elif this_month == '06':
                last_quarter       = str(this_year)     + 'q2'
                last_two_quarter   = str(this_year)     + 'q1'
                last_three_quarter = str(this_year - 1) + 'q4'
                last_four_quarter  = str(this_year - 1) + 'q3'
                last_five_quarter  = str(this_year - 1) + 'q2'

            else:  #this_month == '03':
                last_quarter       = str(this_year)     + 'q1'
                last_two_quarter   = str(this_year - 1) + 'q4'
                last_three_quarter = str(this_year - 1) + 'q3'
                last_four_quarter  = str(this_year - 1) + 'q2'
                last_five_quarter  = str(this_year - 1) + 'q1'

            return last_quarter, last_two_quarter, last_three_quarter, last_four_quarter, last_five_quarter, stock_last_statDate

        # 查财报，返回指定值
        def __get_fundamentals_value(stock_list, myDate):
            '''
            输入 stock_list, 查询日期
            返回指定的财务数据，格式 dict
            '''
            q = query(indicator.code, indicator.inc_net_profit_year_on_year, indicator.statDate
                     ).filter(indicator.code.in_(stock_list))

            df = get_fundamentals(q, statDate = myDate).fillna(value=0)

            tmpDict = df.to_dict()
            stock_dict = {}
            for i in range(len(tmpDict['statDate'].keys())):
                tmpList = []
                tmpList.append(tmpDict['statDate'][i])
                tmpList.append(tmpDict['inc_net_profit_year_on_year'][i])
                stock_dict[tmpDict['code'][i]] = tmpList

            return stock_dict

        # 对净利润增长率进行处理
        def __cal_net_profit_inc(inc_list):

            inc = inc_list

            for i in range(len(inc)):   # 约束在 +- 100 之内，避免失真
                if inc[i] > 100:
                    inc[i] = 100
                if inc[i] < -100:
                    inc[i] = -100

            avg_inc = np.mean(inc[:4])
            last_inc = inc[0]
            inc_std = np.std(inc)

            return avg_inc, last_inc, inc_std

        # 得到最近 n 个季度的统计时间
        last_quarter, last_two_quarter, last_three_quarter, last_four_quarter, last_five_quarter, stock_last_statDate = __get_quarter(stock_list)

        last_quarter_dict       = __get_fundamentals_value(stock_list, last_quarter)
        last_two_quarter_dict   = __get_fundamentals_value(stock_list, last_two_quarter)
        last_three_quarter_dict = __get_fundamentals_value(stock_list, last_three_quarter)
        last_four_quarter_dict  = __get_fundamentals_value(stock_list, last_four_quarter)
        last_five_quarter_dict  = __get_fundamentals_value(stock_list, last_five_quarter)

        stock_dict = {}
        for stock in stock_list:
            inc_list = []

            if stock in stock_last_statDate:
                if stock in last_quarter_dict:
                    if stock_last_statDate[stock] == last_quarter_dict[stock][0]:
                        inc_list.append(last_quarter_dict[stock][1])

                if stock in last_two_quarter_dict:
                    inc_list.append(last_two_quarter_dict[stock][1])
                else:
                    inc_list.append(0)

                if stock in last_three_quarter_dict:
                    inc_list.append(last_three_quarter_dict[stock][1])
                else:
                    inc_list.append(0)

                if stock in last_four_quarter_dict:
                    inc_list.append(last_four_quarter_dict[stock][1])
                else:
                    inc_list.append(0)

                if stock in last_five_quarter_dict:
                    inc_list.append(last_five_quarter_dict[stock][1])
                else:
                    inc_list.append(0)
            else:
                inc_list = [0, 0, 0, 0]

            # 取得过去4个季度的平均增长，最后1个季度的增长，增长标准差
            avg_inc, last_inc, inc_std = __cal_net_profit_inc(inc_list)

            stock_dict[stock] = {}
            stock_dict[stock]['avg_inc'] = avg_inc
            stock_dict[stock]['last_inc'] = last_inc
            stock_dict[stock]['inc_std'] = inc_std

        return stock_dict

    def fun_cal_stock_PEG(self, context):
        '''计算股票的PEG
        返回一个股票code  和  PEG的字典
        '''

        stock_code_list = context.stock_df['code'].tolist()

        #根据股票代码，计算股票的净利润增占率，返回一次增长率字典
        #
        stock_dict = self.fun_get_inc(context, stock_code_list)
        #log.debug("股票增长率字典:\n %s" % (stock_dict['000001.XSHE']))

        #在全部股票列表中，减去不需要计算的股票
        #stock_code_list =  list(set(stock_code_list).difference(set(self.unuse_PEG_stock_list)))
        #log.debug("删除了不需要计算PEG的股票，stock_code_list:\n %s" % (stock_code_list[:2]))

        #获取所有股票的市盈率
        pe_df = context.stock_df.loc[:,['code', 'pe_ratio']]
        #log.debug("股票的市盈率df:\n %s\n" % (pe_df[:2]))

        pe_dict = pe_df.to_dict()
        #log.debug("pe_dict\n%s\n" % (pe_dict))

        #获取股票分红信息
        fh_df = g.QuantLib.fun_get_Divid_by_year(context, stock_code_list)
        #log.debug("fun_get_Divid_by_year df: %s\n" % (df[:5]))
        fh_Dict = fh_df.to_dict()

        stock_interest = {}
        for stock in fh_Dict['divpercent']:
            stock_interest[stock] = fh_Dict['divpercent'][stock]

        h = history(1, '1d', 'close', stock_code_list, df=False)
        #log.debug("stock_history: %s\n" % (h))
        PEG = {}
        for stock_code in stock_code_list:
            avg_inc  = stock_dict[stock_code]['avg_inc']
            last_inc = stock_dict[stock_code]['last_inc']
            inc_std  = stock_dict[stock_code]['inc_std']

            pe = -1
            if stock_code in pe_dict:
                pe = pe_dict[stock_code]

            interest = 0
            if stock_code in stock_interest:
                interest = stock_interest[stock_code]

            PEG[stock_code] = -1
            '''
            原话大概是：
            1、增长率 > 50 的公司要小心，高增长不可持续，一旦转差就要卖掉；实现的时候，直接卖掉增长率 > 50 个股票
            2、增长平稳，不知道该怎么表达，用了 inc_std < last_inc。有思路的同学请告诉我
            '''
            if pe > 0 and last_inc <= 50 and last_inc > 0 and inc_std < last_inc:
                PEG[stock_code] = (pe / (last_inc + interest*100))

        peg_df = pd.DataFrame.from_dict(PEG, 'index')

        #把index当做索引插入一列，方便合并
        peg_df.insert(0, 'code', peg_df.index.tolist())
        #修改列名， 设置索引列
        peg_df.columns=['code', 'PEG']
        peg_df.set_index('code')
        #合并

        log.debug("peg_df:\n %s\n" % (peg_df[:2]))
        #log.debug("未添加PEG的df:\n %s\n" % (context.stock_df[:2]))

        #合并计算的PEG
        context.stock_df = pd.merge(context.stock_df, peg_df, on=['code', 'code'])

        #log.debug("添加PEG的df:\n %s\n" % (context.stock_df[:2]))
        #log.debug("PEG字典:\n %s\n" % (PEG['000002.XSHE']))


    def get_unuse_PEG_stock_list(self):
        '''获取不去要计算PEG的股票代码列表
            主要是上市不足60天的股票
        '''

        #剔除已经停盘的股票
        #stock_list = g.QuantLib.unpaused(stock_list)
        #获取周期性行业，这类股票不太适合PEG选股
        self.unuse_PEG_stock_list = g.QuantLib.fun_get_cycle_industry()
        log.info(self.unuse_PEG_stock_list[:2])


    def fun_assetAllocationSystem(self, context, buylist):

        def __fun_getEquity_ratio(context, __stocklist):
            __ratio = {}
            # 按风险平价配仓
            if __stocklist:
                __ratio = g.QuantLib.fun_calStockWeight_by_risk(context, 2.58, __stocklist)

            return __ratio

        equity_ratio = __fun_getEquity_ratio(context, buylist)
        bonds_ratio  = __fun_getEquity_ratio(context, context.lowPEG_moneyfund)

        return equity_ratio, bonds_ratio

    def fun_calPosition(self, context, equity_ratio, bonds_ratio, lowPEG_ratio, portfolio_value):

        risk_ratio = len(equity_ratio.keys())
        risk_money = context.portfolio.portfolio_value * risk_ratio * context.lowPEG_ratio * context.lowPEG_risk_ratio
        maxrisk_money = risk_money * 1.7

        equity_value = 0
        if equity_ratio:
            equity_value = g.QuantLib.fun_getEquity_value(equity_ratio, risk_money, maxrisk_money, context.lowPEG_confidencelevel)

        value_ratio = 0
        total_value = portfolio_value * lowPEG_ratio
        if equity_value > total_value:
            bonds_value = 0
            value_ratio = 1.0 * lowPEG_ratio
        else:
            value_ratio = (equity_value / total_value) * lowPEG_ratio
            bonds_value = total_value - equity_value

        trade_ratio = {}
        equity_list = equity_ratio.keys()
        for stock in equity_list:
            if stock in trade_ratio:
                trade_ratio[stock] += round((equity_ratio[stock] * value_ratio), 3)
            else:
                trade_ratio[stock] = round((equity_ratio[stock] * value_ratio), 3)

        for stock in bonds_ratio.keys():
            if stock in trade_ratio:
                trade_ratio[stock] += round((bonds_ratio[stock] * bonds_value / total_value) * lowPEG_ratio, 3)
            else:
                trade_ratio[stock] = round((bonds_ratio[stock] * bonds_value / total_value) * lowPEG_ratio, 3)

        return trade_ratio

class QuantLib():
    '''大概是一个工具类'''

    def __init__(self, _period = '1d'):
        pass


    def fun_get_cycle_industry(self):
        '''获得周期性行业'''

        cycle_stock_list = []
        #周期性行业定义
        cycle_industry = [#'A01', #	农业 	1993-09-17
                          #'A02', # 林业 	1996-12-06
                          #'A03', #	畜牧业 	1997-06-11
                          #'A04', #	渔业 	1993-05-07
                          #'A05', #	农、林、牧、渔服务业 	1997-05-30
                          'B06', # 煤炭开采和洗选业 	1994-01-06
                          'B07', # 石油和天然气开采业 	1996-06-28
                          'B08', # 黑色金属矿采选业 	1997-07-08
                          'B09', # 有色金属矿采选业 	1996-03-20
                          'B11', # 开采辅助活动 	2002-02-05
                          #'C13', #	农副食品加工业 	1993-12-15
                          #C14 	食品制造业 	1994-08-18
                          #C15 	酒、饮料和精制茶制造业 	1992-10-12
                          #C17 	纺织业 	1992-06-16
                          #C18 	纺织服装、服饰业 	1993-12-31
                          #C19 	皮革、毛皮、羽毛及其制品和制鞋业 	1994-04-04
                          #C20 	木材加工及木、竹、藤、棕、草制品业 	2005-05-10
                          #C21 	家具制造业 	1996-04-25
                          #C22 	造纸及纸制品业 	1993-03-12
                          #C23 	印刷和记录媒介复制业 	1994-02-24
                          #C24 	文教、工美、体育和娱乐用品制造业 	2007-01-10
                          'C25', # 石油加工、炼焦及核燃料加工业 	1993-10-25
                          'C26', # 化学原料及化学制品制造业 	1990-12-19
                          #C27 	医药制造业 	1993-06-29
                          'C28', # 化学纤维制造业 	1993-07-28
                          'C29', # 橡胶和塑料制品业 	1992-08-28
                          'C30', # 非金属矿物制品业 	1992-02-28
                          'C31', # 黑色金属冶炼及压延加工业 	1994-01-06
                          'C32', # 有色金属冶炼和压延加工业 	1996-02-15
                          'C33', # 金属制品业 	1993-11-30
                          'C34', # 通用设备制造业 	1992-03-27
                          'C35', # 专用设备制造业 	1992-07-01
                          'C36', # 汽车制造业 	1992-07-24
                          'C37', # 铁路、船舶、航空航天和其它运输设备制造业 	1992-03-31
                          'C38', # 电气机械及器材制造业 	1990-12-19
                          #C39 	计算机、通信和其他电子设备制造业 	1990-12-19
                          #C40 	仪器仪表制造业 	1993-09-17
                          'C41', # 其他制造业 	1992-08-14
                          #C42 	废弃资源综合利用业 	2012-10-26
                          'D44', # 电力、热力生产和供应业 	1993-04-16
                          #D45 	燃气生产和供应业 	2000-12-11
                          #D46 	水的生产和供应业 	1994-02-24
                          'E47', # 房屋建筑业 	1993-04-29
                          'E48', # 土木工程建筑业 	1994-01-28
                          'E50', # 建筑装饰和其他建筑业 	1997-05-22
                          #F51 	批发业 	1992-05-06
                          #F52 	零售业 	1992-09-02
                          'G53', # 铁路运输业 	1998-05-11
                          'G54', # 道路运输业 	1991-01-14
                          'G55', # 水上运输业 	1993-11-19
                          'G56', # 航空运输业 	1997-11-05
                          'G58', # 装卸搬运和运输代理业 	1993-05-05
                          #G59 	仓储业 	1996-06-14
                          #H61 	住宿业 	1993-11-18
                          #H62 	餐饮业 	1997-04-30
                          #I63 	电信、广播电视和卫星传输服务 	1992-12-02
                          #I64 	互联网和相关服务 	1992-05-07
                          #I65 	软件和信息技术服务业 	1992-08-20
                          'J66', # 货币金融服务 	1991-04-03
                          'J67', # 资本市场服务 	1994-01-10
                          'J68', # 保险业 	2007-01-09
                          'J69', # 其他金融业 	2012-10-26
                          'K70', # 房地产业 	1992-01-13
                          #L71 	租赁业 	1997-01-30
                          #L72 	商务服务业 	1996-08-29
                          #M73 	研究和试验发展 	2012-10-26
                          'M74', # 专业技术服务业 	2007-02-15
                          #N77 	生态保护和环境治理业 	2012-10-26
                          #N78 	公共设施管理业 	1992-08-07
                          #P82 	教育 	2012-10-26
                          #Q83 	卫生 	2007-02-05
                          #R85 	新闻和出版业 	1992-12-08
                          #R86 	广播、电视、电影和影视录音制作业 	1994-02-24
                          #R87 	文化艺术业 	2012-10-26
                          #S90 	综合 	1990-12-10
                          ]

        for industry in cycle_industry:
            #获取在给定日期一个行业的所有股票，  industry 是 行业代码
            unuse_stocks = get_industry_stocks(industry)
            #两个list的并集
            cycle_stock_list = list(set(cycle_stock_list).union(set(unuse_stocks)))

        #print ("PEG 不考虑的周期类股票")
        #log.info(cycle_stock_list[:1])
        return cycle_stock_list

    def fun_do_trade(self, context, trade_ratio, moneyfund):

        def __fun_tradeStock(context, stock, ratio):
            total_value = context.portfolio.portfolio_value
            if stock in moneyfund:
                self.fun_tradeBond(context, stock, total_value * ratio)
            else:
                curPrice = history(1,'1d', 'close', stock, df=False)[stock][-1]
                curValue = context.portfolio.positions[stock].total_amount * curPrice
                Quota = total_value * ratio
                if Quota:
                    if abs(Quota - curValue) / Quota >= 0.25:
                        if Quota > curValue:
                            cash = context.portfolio.cash
                            if cash >= Quota * 0.25:
                                self.fun_trade(context, stock, Quota)
                        else:
                            self.fun_trade(context, stock, Quota)
                else:
                    self.fun_trade(context, stock, Quota)

        trade_list = trade_ratio.keys()

        myholdstock = context.portfolio.positions.keys()
        total_value = context.portfolio.portfolio_value

        # 已有仓位
        holdDict = {}
        h = history(1, '1d', 'close', myholdstock, df=False)
        for stock in myholdstock:
            tmpW = round((context.portfolio.positions[stock].total_amount * h[stock])/total_value, 2)
            holdDict[stock] = float(tmpW)

        # 对已有仓位做排序
        tmpDict = {}
        for stock in holdDict:
            if stock in trade_ratio:
                tmpDict[stock] = round((trade_ratio[stock] - holdDict[stock]), 2)
        tradeOrder = sorted(tmpDict.items(), key=lambda d:d[1], reverse=False)

        _tmplist = []
        for idx in tradeOrder:
            stock = idx[0]
            __fun_tradeStock(context, stock, trade_ratio[stock])
            _tmplist.append(stock)

        # 交易其他股票
        for i in range(len(trade_list)):
            stock = trade_list[i]
            if len(_tmplist) != 0 :
                if stock not in _tmplist:
                    __fun_tradeStock(context, stock, trade_ratio[stock])
            else:
                __fun_tradeStock(context, stock, trade_ratio[stock])

    def fun_getEquity_value(self, equity_ratio, risk_money, maxrisk_money, confidence_ratio):
        def __fun_getdailyreturn(stock, freq, lag):
            hStocks = history(lag, freq, 'close', stock, df=True)
            dailyReturns = hStocks.resample('D',how='last').pct_change().fillna(value=0, method=None, axis=0).values

            return dailyReturns

        def __fun_get_portfolio_dailyreturn(ratio, freq, lag):
            __portfolio_dailyreturn = []
            for stock in ratio.keys():
                if ratio[stock] != 0:
                    __dailyReturns = __fun_getdailyreturn(stock, freq, lag)
                    __tmplist = []
                    for i in range(len(__dailyReturns)):
                        __tmplist.append(__dailyReturns[i] * ratio[stock])
                    if __portfolio_dailyreturn:
                        __tmplistB = []
                        for i in range(len(__portfolio_dailyreturn)):
                            __tmplistB.append(__portfolio_dailyreturn[i]+__tmplist[i])
                        __portfolio_dailyreturn = __tmplistB
                    else:
                        __portfolio_dailyreturn = __tmplist

            return __portfolio_dailyreturn

        def __fun_get_portfolio_ES(ratio, freq, lag, confidencelevel):
            if confidencelevel == 1.96:
                a = (1 - 0.95)
            elif confidencelevel == 2.06:
                a = (1 - 0.96)
            elif confidencelevel == 2.18:
                a = (1 - 0.97)
            elif confidencelevel == 2.34:
                a = (1 - 0.98)
            elif confidencelevel == 2.58:
                a = (1 - 0.99)
            else:
                a = (1 - 0.95)
            dailyReturns = __fun_get_portfolio_dailyreturn(ratio, freq, lag)
            dailyReturns_sort =  sorted(dailyReturns)

            count = 0
            sum_value = 0
            for i in range(len(dailyReturns_sort)):
                if i < (lag * a):
                    sum_value += dailyReturns_sort[i]
                    count += 1
            if count == 0:
                ES = 0
            else:
                ES = -(sum_value / (lag * a))

            return ES

        def __fun_get_portfolio_VaR(ratio, freq, lag, confidencelevel):
            __dailyReturns = __fun_get_portfolio_dailyreturn(ratio, freq, lag)
            __portfolio_VaR = 1.0 * confidencelevel * np.std(__dailyReturns)

            return __portfolio_VaR

        # 每元组合资产的 VaR
        __portfolio_VaR = __fun_get_portfolio_VaR(equity_ratio, '1d', 180, confidence_ratio)

        __equity_value_VaR = 0
        if __portfolio_VaR:
            __equity_value_VaR = risk_money / __portfolio_VaR

        __portfolio_ES = __fun_get_portfolio_ES(equity_ratio, '1d', 180, confidence_ratio)

        __equity_value_ES = 0
        if __portfolio_ES:
            __equity_value_ES = maxrisk_money / __portfolio_ES

        if __equity_value_VaR == 0:
            equity_value = __equity_value_ES
        elif __equity_value_ES == 0:
            equity_value = __equity_value_VaR
        else:
            equity_value = min(__equity_value_VaR, __equity_value_ES)

        return equity_value

    def fun_get_Divid_by_year(self, context, stocks):
        '''
            stocks  股票代码列表
            逐年获取股票的分红信息
        '''

        year = context.current_dt.year - 1

        #log.debug("year : %s" % (year))

        #将当前股票池转换为国泰安的6位股票池
        #主要是将000001.XSHE  转换成 000001
        stocks_symbol=[]
        #log.debug("转换前股票代码 : %s" % (stocks[:5]))
        for s in stocks:
            stocks_symbol.append(s[0:6])

        #log.debug("转换后股票代码 : %s" % (stocks_symbol[:5]))

        df = gta.run_query(query(
                gta.STK_DIVIDEND.SYMBOL,                # 股票代码
                gta.STK_DIVIDEND.DECLAREDATE,           # 分红消息的时间
            ).filter(
                gta.STK_DIVIDEND.ISDIVIDEND == 'Y',     #有分红的股票
                gta.STK_DIVIDEND.DIVDENDYEAR == year,
                gta.STK_DIVIDEND.TERMCODE == 'P2702',   # 年度分红
                gta.STK_DIVIDEND.SYMBOL.in_(stocks_symbol)
            )).fillna(value=0, method=None, axis=0)
        # 转换时间格式
        df['pubtime'] = map(lambda x: int(x.split('-')[0]+x.split('-')[1]+x.split('-')[2]),df['DECLAREDATE'])
        # 取得当前时间
        currenttime  = int(str(context.current_dt)[0:4]+str(context.current_dt)[5:7]+str(context.current_dt)[8:10])
        # 选择在当前时间能看到的记录
        df = df[(df.pubtime < currenttime)]
        # 得到目前看起来，有上一年度年度分红的股票
        stocks_symbol_this_year = list(df['SYMBOL'])
        # 得到目前看起来，上一年度没有年度分红的股票
        stocks_symbol_past_year = list(set(stocks_symbol) - set(stocks_symbol_this_year))

        # 查有上一年度年度分红的
        df1 = gta.run_query(query(
                gta.STK_DIVIDEND.SYMBOL,                # 股票代码
                gta.STK_DIVIDEND.DIVIDENTBT,            # 股票分红
                gta.STK_DIVIDEND.DECLAREDATE,           # 分红消息的时间
                gta.STK_DIVIDEND.DISTRIBUTIONBASESHARES # 分红时的股本基数
            ).filter(
                gta.STK_DIVIDEND.ISDIVIDEND == 'Y',     #有分红的股票
                gta.STK_DIVIDEND.DIVDENDYEAR == year,
                gta.STK_DIVIDEND.SYMBOL.in_(stocks_symbol_this_year)
            )).fillna(value=0, method=None, axis=0)

        df1['pubtime'] = map(lambda x: int(x.split('-')[0]+x.split('-')[1]+x.split('-')[2]),df1['DECLAREDATE'])
        currenttime  = int(str(context.current_dt)[0:4]+str(context.current_dt)[5:7]+str(context.current_dt)[8:10])
        df1 = df1[(df1.pubtime < currenttime)]

        # 求上上年的年度分红
        df2 = gta.run_query(query(
                gta.STK_DIVIDEND.SYMBOL,                # 股票代码
                gta.STK_DIVIDEND.DIVIDENTBT,            # 股票分红
                gta.STK_DIVIDEND.DECLAREDATE,           # 分红消息的时间
                gta.STK_DIVIDEND.DISTRIBUTIONBASESHARES # 分红时的股本基数
            ).filter(
                gta.STK_DIVIDEND.ISDIVIDEND == 'Y',     #有分红的股票
                gta.STK_DIVIDEND.DIVDENDYEAR == (year - 1),
                gta.STK_DIVIDEND.SYMBOL.in_(stocks_symbol_past_year)
            )).fillna(value=0, method=None, axis=0)

        df2['pubtime'] = map(lambda x: int(x.split('-')[0]+x.split('-')[1]+x.split('-')[2]),df2['DECLAREDATE'])
        currenttime  = int(str(context.current_dt)[0:4]+str(context.current_dt)[5:7]+str(context.current_dt)[8:10])
        df2 = df2[(df2.pubtime < currenttime)]

        df= pd.concat((df2,df1))

        df['SYMBOL']=map(normalize_code,list(df['SYMBOL']))
        df.index=list(df['SYMBOL'])

        # 获取最新股本
        q = query(valuation.code, valuation.capitalization
                ).filter(valuation.code.in_(list(df.index)))

        df3 = get_fundamentals(q).fillna(value=0)
        df3['SYMBOL'] = df3['code']
        df3 = df3.drop(['code'], axis=1)

        # 合并成一个 dataframe
        df = df.merge(df3,on='SYMBOL')
        df.index = list(df['SYMBOL'])

        # 转换成 float
        df['DISTRIBUTIONBASESHARES'] = map(float, df['DISTRIBUTIONBASESHARES'])
        # 计算股份比值
        df['CAP_RATIO'] = df['DISTRIBUTIONBASESHARES'] / (df['capitalization'] * 10000)

        df['DIVIDENTBT'] = map(float, df['DIVIDENTBT'])
        # 计算相对于目前股份而言的分红额度
        df['DIVIDENTBT'] = df['DIVIDENTBT'] * df['CAP_RATIO']
        df = df.drop(['SYMBOL','DECLAREDATE','DISTRIBUTIONBASESHARES','capitalization','CAP_RATIO'], axis=1)

        #接下来这一步是考虑多次分红的股票，因此需要累加股票的多次分红
        df = df.groupby(df.index).sum()

        #得到当前股价
        Price=history(1, unit='1d', field='close', security_list=list(df.index), df=True, skip_paused=False, fq='pre')
        Price=Price.T

        df['pre_close']=Price

        #计算股息率 = 股息/股票价格，* 10 是因为取到的是每 10 股分红
        df['divpercent']=df['DIVIDENTBT']/(df['pre_close'] * 10)

        df['code'] = np.array(df.index)

        return df

    def fun_calStockWeight_by_risk(self, context, confidencelevel, stocklist):

        '''根据风险，计算股票权重
        :param context: 上下文
        :param confidencelevel: 置信率
        :param stocklist: 股票列表
        :return:
        '''
        def __fun_calstock_risk_ES(stock, lag, confidencelevel):

            """
            根据计算股票的风险ES
            :param stock: 股票代码
            :param lag: 180， 所查看历史数据的周期，就是history中历史数据的记录数，如果后面是1d，那么就是向前追溯180d
            :param confidencelevel: 置信率
            :return: 返回股票的风险ES
            """

            #取得股票的历史数据，缺省关注收盘价，参数lag缺省180d
            hStocks = history(lag, '1d', 'close', stock, df=True)

            #下面的一段代码不知道什么意思？？？？？
            dailyReturns = hStocks.resample('D',how='last').pct_change().fillna(value=0, method=None, axis=0).values
            if confidencelevel   == 1.96:
                a = (1 - 0.95)
            elif confidencelevel == 2.06:
                a = (1 - 0.96)
            elif confidencelevel == 2.18:
                a = (1 - 0.97)
            elif confidencelevel == 2.34:
                a = (1 - 0.98)
            elif confidencelevel == 2.58:
                a = (1 - 0.99)
            elif confidencelevel == 5:
                a = (1 - 0.99999)
            else:
                a = (1 - 0.95)

            dailyReturns_sort =  sorted(dailyReturns)

            count = 0
            sum_value = 0
            for i in range(len(dailyReturns_sort)):
                if i < (lag * a):
                    sum_value += dailyReturns_sort[i]
                    count += 1
            if count == 0:
                ES = 0
            else:
                ES = -(sum_value / (lag * a))

            if isnan(ES):
                ES = 0

            return ES

        def __fun_calstock_risk_VaR(stock):
            hStocks = history(180, '1d', 'close', stock, df=True)
            dailyReturns = hStocks.resample('D',how='last').pct_change().fillna(value=0, method=None, axis=0).values
            VaR = 1 * 2.58 * np.std(dailyReturns)

            return VaR

        __risk = {}

        stock_list = []
        for stock in stocklist:
            curRisk = __fun_calstock_risk_ES(stock, 180, confidencelevel)

            if curRisk <> 0.0:
                __risk[stock] = curRisk

        __position = {}
        for stock in __risk.keys():
            __position[stock] = 1.0 / __risk[stock]

        total_position = 0
        for stock in __position.keys():
            total_position += __position[stock]

        __ratio = {}
        for stock in __position.keys():
            tmpRatio = __position[stock] / total_position
            if isnan(tmpRatio):
                tmpRatio = 0
            __ratio[stock] = round(tmpRatio, 4)

        return __ratio

    def fun_tradeBond(self, context, stock, Value):
        hStocks = history(1, '1d', 'close', stock, df=False)
        curPrice = hStocks[stock]
        curValue = float(context.portfolio.positions[stock].total_amount * curPrice)
        deltaValue = abs(Value - curValue)
        if deltaValue > (curPrice*100):
            if Value > curValue:
                cash = context.portfolio.cash
                if cash > (curPrice*100):
                    self.fun_trade(context, stock, Value)
            else:
                # 如果是银华日利，多卖 100 股，避免个股买少了
                if stock == '511880.XSHG':
                    Value -= curPrice*100
                self.fun_trade(context, stock, Value)


    def fun_delNewShare(self, context, equity, deltaday):
        '''
        剔除上市时间较短的产品
        从 equity 中删除上市时间少于 deltaday天的产品
        返回符合要求的产品list
        '''
        deltaDate = context.current_dt.date() - dt.timedelta(deltaday)

        tmpList = []
        for stock in equity:
            if get_security_info(stock).start_date < deltaDate:
                tmpList.append(stock)

        return tmpList

    def unpaused(self, _stocklist):
        '''删除当天已经停盘的股票'''
        current_data = get_current_data()
        return [s for s in _stocklist if not current_data[s].paused]

    def fun_trade(self, context, stock, value):
        self.fun_setCommission(context, stock)
        order_target_value(stock, value)

    def fun_setCommission(self, context, stock):
        if stock in context.lowPEG_moneyfund:
            set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0, close_commission=0, close_today_commission=0, min_commission=0), type='stock')
        else:
            set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5), type='stock')
