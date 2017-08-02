import torch.nn as nn
import numpy as np
import torch,os,pickle,json,time,argparse
from utils import *
from data_loader import * #get_loader,validation_split
from build_vocab import Vocabulary
from build_vocab import build_vocab
from model import EncoderCNN, DecoderRNN 
from torch.autograd import Variable 
from torch.nn.utils.rnn import pack_padded_sequence
from torchvision import transforms
from pycrayon import CrayonClient

def to_var(x,volatile=False):
    if torch.cuda.is_available():
        x = x.cuda()
    return Variable(x,volatile=volatile)

def main(args):

    #setup tensorboard
    if args.tensorboard:
        cc = CrayonClient(hostname="localhost")
        print(cc.get_experiment_names())
    #if args.name in cc.get_experiment_names():
        try:
            cc.remove_experiment(args.name)
        except:
            print("experiment didnt exist")
        cc_server = cc.create_experiment(args.name)

    # Create model directory
    full_model_path = args.model_path+ "/" +args.name
    if not os.path.exists(full_model_path):
        os.makedirs(full_model_path)
    with open(full_model_path+"/parameters.json", 'w') as f:
        f.write((json.dumps(vars(args))))

    # Image preprocessing

    transform = transforms.Compose([ 
        #transforms.Scale(args.crop_size),
        transforms.ToTensor()])
        #transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
    mini_transform = transforms.Compose([ 
        transforms.ToPILImage(),
        transforms.Scale(20),
        transforms.ToTensor() ])
    
    # Load vocabulary wrapper.
    if args.vocab_path is not None:
        with open(args.vocab_path, 'rb') as f:
            vocab = pickle.load(f)
    else:
        print("building new vocab")
        vocab = build_vocab(args.image_dir,1,None)
        with open((full_model_path+"/vocab.pkl"), 'wb') as f:
            pickle.dump(vocab, f)

    
    # Build data loader
    data_loader = get_loader(args.image_dir,  vocab, transform, args.batch_size, shuffle=True, num_workers=args.num_workers) 
    code_data_set = ProcessingDataset(root=args.image_dir, vocab=vocab, transform=transform)
    train_ds, val_ds = validation_split(code_data_set)
    train_loader = torch.utils.data.DataLoader(train_ds,collate_fn=collate_fn)
    test_loader = torch.utils.data.DataLoader(val_ds,collate_fn=collate_fn)
    train_size = len(train_loader)
    test_size = len(test_loader)

    # Build the models
    #encoder = EncoderCNN(args.embed_size,args.train_cnn)
    #print(encoder)
    decoder = DecoderRNN(args.embed_size, args.hidden_size, len(vocab), args.num_layers,vocab)
    decoder = decoder
    print(decoder)
    if torch.cuda.is_available():
        #encoder.cuda()
        decoder.cuda()

    # Loss and Optimizer
    #criterion = nn.CrossEntropyLoss()
    criterion = nn.MSELoss()
    #criterion = nn.SmoothL1Loss()
    #params = list(decoder.parameters()) + list(encoder.linear.parameters()) + list(encoder.bn.parameters())
    params = list(decoder.parameters()) #+ list(encoder.linear.parameters()) + list(encoder.bn.parameters())
    optimizer = torch.optim.Adam(params, lr=args.learning_rate)
    start_time = time.time()
    
    # Train the Models
    total_step = len(data_loader)
    for epoch in range(args.num_epochs):
        for i, (images, captions, lengths) in enumerate(data_loader):
            decoder.train()
            #encoder.train()
            # Set mini-batch dataset
            #image_ts = to_var(images, volatile=True)
            image_ts = to_var(images)
            #print("captoins lenrgth:"+str(captions.size()))
            captions = to_var(captions)
            #print("padded captions lenrgth:"+str(targets.size()))
            count = images.size()[0]
            
            # Forward, Backward and Optimize
            decoder.zero_grad()
            #encoder.zero_grad()
            #features = encoder(image_ts)
            #print("image_ts size"+str(image_ts.size()))
            #print("features size"+str(features.size()))
            outputs = decoder(captions, lengths)
            #outputs = decoder(image_ts.view(image_ts.size()[0],-1), captions, lengths)
            #print("image size:" +str(images.size()))
            #print("targets size:" +str(targets.size()))

            #loss = criterion(outputs, targets)
            loss = criterion(outputs, image_ts)
            loss.backward()
            optimizer.step()

            total = captions.size(0)
            correct = outputs.data.eq(image_ts.data).sum()
            accuracy = 100.*correct/total
            #accuracy =0.0
            #print(image_ts.data[0].equal(image_ts.data[-1]))
            #print("WTF")
            #print(outputs.data[0].equal(outputs.data[-1]))
            #print(outputs.size())

            if args.tensorboard:
                cc_server.add_scalar_value("train_loss", loss.data[0])
                cc_server.add_scalar_value("perplexity", np.exp(loss.data[0]))
                cc_server.add_scalar_value("accuracy", accuracy)

            # Print log info
            if i % args.log_step == 0:
                #print("i "+str(i))
                #torch.set_printoptions(profile="full")
                for ii,t in enumerate(outputs):
                    result = transforms.ToPILImage()(t.data.cpu())
                    result.save("./results/"+str(i)+"_"+str(ii)+".png")
                    origin = transforms.ToPILImage()(image_ts[ii].data.cpu())
                    origin.save("./results/"+str(i)+"_"+str(ii)+"target.png")
                    with open(("./results/"+str(i)+"_"+str(ii)+"_diff.txt"), 'w') as f:
                        #f.write(str(torch.abs(t-image_ts[ii])))
                        f.write(str(torch.abs(t-image_ts[ii]).sum()))
                        #f.write(str(t))
                        #f.write(str(image_ts))


                #print("first output"+str(outputs[0]))
                #print("target:"+str(image_ts[0]))
                #print("diff:"+str(outputs[0]-image_ts[0]))
                #print("diff sum:"+str((outputs-image_ts).sum()))
                print('Epoch [%d/%d], Step [%d/%d], Loss: %.4f, accuracy: %2.2f Perplexity: %5.4f'
                      %(epoch, args.num_epochs, i, total_step, 
                        loss.data[0], accuracy, np.exp(loss.data[0]))) 
                
            # Save the models
            if (i+1) % args.save_step == 0:
                torch.save(decoder.state_dict(), 
                           os.path.join(full_model_path, 
                                        'decoder-%d-%d.pkl' %(epoch+1, i+1)))
                #torch.save(encoder.state_dict(), os.path.join(full_model_path, 'encoder-%d-%d.pkl' %(epoch+1, i+1)))
                           
    add_log_entry(args.name,start_time,vars(args))
    torch.save(decoder.state_dict(), os.path.join(full_model_path, 'decoder-%d-%d.pkl' %(epoch+1, i+1)))
    #torch.save(encoder.state_dict(), os.path.join(full_model_path, 'encoder-%d-%d.pkl' %(epoch+1, i+1)))
    end_time = time.time()
    print("finished training, runtime: %d",[(end_time-start_time)])
                
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_path', type=str, default='./models/' ,
                        help='path for saving trained models')
    parser.add_argument('--name', type=str,required=True ,
                        help='name of model')
    parser.add_argument('--crop_size', type=int, default=224 ,
                        help='size for randomly cropping images')
    parser.add_argument('--vocab_path', type=str, help='path for vocabulary wrapper')
    parser.add_argument('--image_dir', type=str, help='directory for images')
    parser.add_argument('--log_step', type=int , default=10,
                        help='step size for prining log info')
    parser.add_argument('--save_step', type=int , default=1000,
                        help='step size for saving trained models')
    # Model parameters
    parser.add_argument('--embed_size', type=int , default=256 ,
                        help='dimension of word embedding vectors')
    parser.add_argument('--hidden_size', type=int , default=512 ,
                        help='dimension of lstm hidden states')
    parser.add_argument('--num_layers', type=int , default=1 ,
                        help='number of layers in lstm')
    parser.add_argument('-n','--notes', type=str ,required=True,
                        help='commit message')
    parser.add_argument('--loss', type=str, help='use my special loss')
    
    parser.add_argument('--num_epochs', type=int, default=5)
    parser.add_argument('--batch_size', type=int, default=128)
    parser.add_argument('--num_workers', type=int, default=2)
    parser.add_argument('--learning_rate', type=float, default=0.001)
    parser.add_argument('--tensorboard', type=str)
    parser.add_argument('--train_cnn', action="store_false")
    args = parser.parse_args()
    print(args)
    main(args)
